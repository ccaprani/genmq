"""
genquiz is a module for generating Moodle Quizes using a pre-prepared LaTeX
template file with variables that are populated from a csv database. The script
produces a merged XML file for uploading to Moodle to create the quiz.
"""

import xml.etree.ElementTree as ET
import argparse

import tempfile
import time
import glob
import os
import jinja2  # https://tug.org/tug2019/slides/slides-ziegenhagen-python.pdf
import shutil
import subprocess
import stat
import pandas as pd
import uuid


def remove_readonly(func, path, excinfo):
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
    df = pd.read_csv(csvfile,dtype=str)
    keys = list(df.columns.values)

    return df, keys


def gen_files(values, keys, template, delete_temps, pythontex):
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

    Returns
    -------
    None.

    """

    # Change method of assigning tmpfile names
    tmpfile = next(tempfile._get_candidate_names())
    # tmpfile = str(uuid.uuid4())

    # Create tex file
    render_file(values, keys, template, tmpfile)

    try:
        compile_files(values, tmpfile, pythontex)

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


def compile_files(values, tmpfile, pythontex=True):
    """
    Generates the Questions and Answers documents for a student

    Parameters
    ----------
    values : tuple of string
        Contains student's data: Moodle ID, Full Name, Student ID.
    tmpfile : string
        Name of the temporary files.

    Returns
    -------
    None.

    """

    # Compilation commands
    cmd_stem = " %s.tex" % tmpfile
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
    # SHould update to use the Popen function, and evaluate the returned args
    subprocess.call(cmd_pdflatex, shell=True)
    if pythontex:
        subprocess.call(cmd_pythontex, shell=True)
        subprocess.call(cmd_pdflatex, shell=True)

    # file_mask = params.file_mask
    # folder_mask = params.folder_mask
    # if not args.generic:
    #     file_mask += params.sol_stem

    # move_pdf(
    #     tmpfile, params.root, demask(values, file_mask), demask(values, folder_mask)
    # )

    # if params.gen_paper and not params.generic:
    #     # Compile test only, removing solutions
    #     set_hidden(tmpfile + ".tex", hidden=True)

    #     # Now compile LaTeX ONLY (to avoid generating any new random variables)
    #     # Do it twice to update toc
    #     subprocess.call(cmd_pdflatex, shell=True)
    #     subprocess.call(cmd_pdflatex, shell=True)

    #     # reset file mask
    #     file_mask = params.file_mask + params.paper_stem

    #     move_pdf(
    #         tmpfile,
    #         params.questdir,
    #         demask(values, file_mask),
    #         demask(values, folder_mask),
    #     )


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
    document = document.replace(r"\usepackage[draft]{moodle}", r"\usepackage{moodle}")

    # write document
    with open(tmpfile + ".tex", "w", encoding="utf-8") as outfile:
        outfile.write(document)


def merge_xml():
    """
    Merges all the Moodle quiz xml files in the folder into one, saves the 
    merged file, and deletes the temporary files.
    """

    # Find all xml files in the folder - ASSUMES no other xml files
    xml_files = glob.glob("*.xml")
    roots = [ET.parse(f).getroot() for f in xml_files]
    base = roots[0]
    for r in roots[1:]:
        for el in r:
            if el.tag == "question" and el.attrib["type"] != "category":
                base.append(el)

    base_xml = ET.ElementTree(base)
    base_xml.write("genquiz.xml", encoding="utf-8", xml_declaration=True)

    # Now delete the xml files except for the new one
    # Note: will delete XML files already in the folder.
    for f in xml_files:
        os.remove(f)

    pass


def main(args):
    """
    The main driver

    :args: The params passed in
    :returns: None

    """

    t = time.time()

    template = make_template(args.template)

    df, keys = generic(args.csvfile)

    # Apply function to each row of df
    df.apply(
        gen_files, axis=1, keys=keys, template=template, 
        delete_temps=args.delete_temps, pythontex=args.simple
    )

    # Now merge the generated XML files
    merge_xml()

    print("")
    print("*** genquiz has finished ***")
    print(
        "Execution for %d questions generated in %2.0f sec"
        % (len(df.index), time.time() - t)
    )

    pass


if __name__ == "__main__":
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
        help="Whether or not to delete temporary files",
        required=False,
        default=True,
        action="store_false",
    )

    parser.add_argument(
        "-s",
        "--simple",
        help="Whether or not template file requires pythontex",
        required=False,
        default=True,
        action="store_false",
    )

    args = parser.parse_args()

    main(args)
