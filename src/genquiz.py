"""
genquiz is a module for generating Moodle Quizes using a pre-prepared LaTeX
template file with variables that are populated from a csv database. The script
produces a merged XML file for uploading to Moodle to create the quiz.
"""

import xml.etree.ElementTree as ET
import argparse

import tempfile
import time
from pathlib import Path
import glob
import os
import jinja2  # https://tug.org/tug2019/slides/slides-ziegenhagen-python.pdf
import shutil
import subprocess
import stat
from tqdm import tqdm
import pandas as pd
import re

tempxmlfiles = []


def remove_readonly(func, path):
    """Attempts to remove a read-only file by changing the permissions"""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def make_template(texfile):
    """
    Creates the jinja2 template using a redefined template structure that
    plays nicely with LaTeX
    https://web.archive.org/web/20121024021221/http://e6h.de/post/11/

    Parameters
    ----------
    texfile : string
        The template LaTeX file containing jinja template variables.
    tmpfile : string
        The name of the temporary files that will be used.

    Returns
    -------
    jinja2 template
        jinja2 template used to render the documents.

    """
    latex_jinja_env = jinja2.Environment(
        block_start_string=r"\BLOCK{",  # instead of jinja's usual {%
        block_end_string=r"}",  # %}
        variable_start_string=r"\VAR{",  # {{
        variable_end_string=r"}",  # }}
        comment_start_string=r"\#{",  # {#
        comment_end_string=r"}",  # #}
        line_statement_prefix=r"%-",
        line_comment_prefix=r"%#",
        trim_blocks=True,
        autoescape=False,
        undefined=jinja2.DebugUndefined,
        loader=jinja2.FileSystemLoader(os.path.abspath(".")),
    )

    # Load the template from a file
    return latex_jinja_env.get_template(texfile)


def generic(csvfile):
    """
    Processes the csvfile to extract the dataframe and keys for use as a
    generic mail merge application.

    Parameters
    ----------
    csvfile : string
        The name of the worksheet containing the data.

    Returns
    -------
    df : dataframe
        The pandas dataframe object.
    keys : list of strings
        The keys for the data, i.e. the column names, which must be single
        words with no hyphens or underscores (must meet both python variable
        name rules and play nice with LaTeX)

    """
    df = pd.read_csv(csvfile, dtype=str)
    keys = list(df.columns.values)

    return df, keys


def gen_files(values, keys, template, delete_temps, pythontex, logfile):
    """
    Drives the rendering and compilation process for each row, and
    cleans up the files afterwards.

    Parameters
    ----------
    values : tuple of string
        Contains row of data: for student's: Moodle ID, Full Name, Student ID.
    keys : tuple of string
        Contains the field names of the data (i.e. worksheet column names)
    template : jinja2 template
        set to render the LaTeX file.
    tmpfile : string
        Name of the temporary files.
    delete_temps: bool
        Pass-through argument
    logfile: bool
        Pass-through argument

    Returns
    -------
    None.

    """

    # Change method of assigning tmpfile names
    tmpfile = next(tempfile._get_candidate_names())

    # Create tex file
    render_file(values, keys, template, tmpfile)

    try:
        compile_files(tmpfile, pythontex, logfile)

    finally:
        if delete_temps:
            for f in glob.glob(tmpfile + ".*"):
                # Notice that here we want to retain the xml file and pdf for now
                if not f == (tmpfile + ".xml"):
                    os.remove(f)
            path = "comment.cut"
            if os.path.exists(path):
                os.remove(path)
            path = "pythontex-files-" + tmpfile
            if os.path.exists(path):
                shutil.rmtree(path, onerror=remove_readonly)


def compile_files(tmpfile, pythontex=False, logfile=False):
    """
    Generates the quiz question document for a student

    Parameters
    ----------
    tmpfile : string
        Name of the temporary files.
    pythontex : bool
        If pythontex compilation is required.
    logfile : bool
        If recording the LaTeX output

    Returns
    -------
    None.

    """

    # Compilation commands
    cmd_stem = f" {tmpfile}.tex"
    cmd_pdflatex = (
        "pdflatex -shell-escape -synctex=1"  # -enable-write18"
        + "-interaction=nonstopmode"
        + cmd_stem
    )
    cmd_pythontex = "pythontex " + cmd_stem

    # Ensure solutions are not hidden
    # set_hidden(tmpfile + ".tex", hidden=False)

    # Compile full document including solutions
    # This step generates the variables & solutions
    # Should update to use the Popen function, and evaluate the returned args
    output = subprocess.run(cmd_pdflatex, shell=True, capture_output=True)
    if logfile:
        with open("genquiz.log", "wb") as outfile:
            outfile.write(output.stdout)

    if pythontex:
        output = subprocess.run(cmd_pythontex, shell=True, capture_output=True)
        if logfile:
            with open("gq_pythontex.log", "wb") as outfile:
                outfile.write(output.stdout)
        output = subprocess.run(cmd_pdflatex, shell=True, capture_output=True)
        if logfile:
            with open("gq_post_pythontex.log", "wb") as outfile:
                outfile.write(output.stdout)

    tempxmlfiles.append(tmpfile + "-moodle.xml")


def render_file(values, keys, template, tmpfile):
    """
    Renders the tex file for compilation for a specific set of values

    Parameters
    ----------
    values : list of strings
        Contains the values to be placed against each template variable
    keys : list of strings
        Contains template variable names to be replaced
    template : jinja2 template
        sed to render the LaTeX file.
    tmpfile : string
        Name of the temporary files.

    Returns
    -------
    None.

    """

    # combine template and variables
    options = dict(zip(keys, values))
    document = template.render(**options)

    # Here we must swap the draft mode of the Moodle.sty compilation
    # document = document.replace(r"\usepackage[draft]{moodle}", r"\usepackage{moodle}")
    p = re.compile(r"(^\\usepackage\S+)draft(\S+{moodle}$)", re.MULTILINE)
    document = p.sub(r"\1\2", document)
    # In case of empty options remaining
    document = document.replace(r"\usepackage[]{moodle}", r"\usepackage{moodle}")

    # write document
    with open(tmpfile + ".tex", "w", encoding="utf-8") as outfile:
        outfile.write(document)


def merge_xml(delete_temps, stem):
    """
    Merges all the Moodle quiz xml files in the folder into one, saves the
    merged file, and deletes the temporary files.
    """

    # Parse the created XML files
    # xml_files = glob.glob("*.xml")
    xml_files = tempxmlfiles
    roots = [ET.parse(f).getroot() for f in xml_files]
    base = roots[0]
    for r in roots[1:]:
        for el in r:
            if el.tag == "question" and el.attrib["type"] != "category":
                base.append(el)

    base_xml = ET.ElementTree(base)
    base_xml.write(f"{stem}.xml", encoding="utf-8", xml_declaration=True)

    if delete_temps:
        # Now delete the xml files except for the new one
        # Note: will delete XML files already in the folder.
        for f in xml_files:
            os.remove(f)

    pass


def clean_xml_files(warn):
    """
    Remove any XML files already in the folder
    """

    def confirm_prompt(question: str) -> bool:
        reply = None
        while reply not in ("", "y", "n"):
            reply = input(f"{question} (Y/n): ").lower()
        return reply in ("", "y")

    for f in glob.glob(".xml"):
        delete = True
        if warn:
            delete = confirm_prompt(f"Delete {f}?")
        if delete:
            os.remove(f)


def main(args):
    """
    The main driver

    :args: The params passed in
    :returns: None

    """

    # clean_xml_files(args.warn)
    tempxmlfiles = []

    t = time.time()

    # Would be better here to use Path(args.template).resolve() to get the abs
    # path on the file system to all passed-in arguments
    template = make_template(args.template)

    df, keys = generic(args.csvfile)

    df_gq = df if args.number is None else df.iloc[: args.number, :]

    # Create the progress bar
    tqdm.pandas()

    # Apply function to each row of df
    df_gq.progress_apply(
        gen_files,
        axis=1,
        keys=keys,
        template=template,
        delete_temps=args.delete_temps,
        pythontex=args.pythontex,
        logfile=args.log,
    )

    # Now merge the generated XML files
    merge_xml(args.delete_temps, Path(args.template).stem)

    print("")
    print("*** genquiz has finished ***")
    print(
        "Execution for %d questions generated in %2.0f sec"
        % (len(df_gq.index), time.time() - t)
    )

    pass


def cli():
    """
    Command Line Interface for running as script or as command
    """
    parser = argparse.ArgumentParser(
        description="Generate XML file for import as a Moodle Quiz, \
         using a LaTeX template and input csv"
    )
    # Required args
    requiredargs = parser.add_argument_group("required named arguments")
    requiredargs.add_argument(
        "template",
        help="LaTeX Template File with certain commands\
                                  for jinja2 based on Moodle.sty package",
    )
    requiredargs.add_argument(
        "csvfile",
        help="CSV file containing the named variables for the jinja2 template",
    )

    parser.add_argument(
        "-d",
        "--delete_temps",
        help="Do not delete temporary files",
        required=False,
        default=True,
        action="store_false",
    )

    parser.add_argument(
        "-n",
        "--number",
        help="Compile the first n questions in the database",
        required=False,
        type=int,
    )

    parser.add_argument(
        "-p",
        "--pythontex",
        help="Execute compilation twice if pythontex code included in file",
        required=False,
        default=False,
        action="store_false",
    )

    parser.add_argument(
        "-w",
        "--warn",
        help="Warn before overwriting a previous genquiz-moodle.xml file",
        required=False,
        default=True,
        action="store_false",
    )

    parser.add_argument(
        "-l",
        "--log",
        help="Log the LaTeX output to file",
        required=False,
        default=False,
        action="store_true",
    )

    args = parser.parse_args()

    main(args)


if __name__ == "__main__":
    cli()
