"""
genmq is a module for generating Moodle Quizes using a pre-prepared LaTeX
template file with variables that are populated from a csv database. The script
produces a merged XML file for uploading to Moodle to create the quiz.
"""

import copy
import xml.etree.ElementTree as ET
import argparse
import sys
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
import math


class GenMoodleQuiz:
    """
    The main genmq class
    """

    def __init__(self, args):
        """
        :args: The params passed in
        """
        self.templatefile = args.template
        self.csvfile = args.csvfile
        self.compile_number = args.number
        self.delete_temps = args.delete_temps
        self.pythontex = args.pythontex
        self.logfile = args.log
        self.warn = args.warn

        self.tempxmlfiles = []
        self.jinja_template = None

    def run(self):
        """
        The main driver function
        """

        t = time.time()

        # Would be better here to use Path(args.template).resolve() to get the abs
        # path on the file system to all passed-in arguments

        self.jinja_template = self.make_template(self.templatefile)
        df, keys = self.generic(self.csvfile)

        df_gq = df if self.compile_number is None else df.head(self.compile_number)

        # Create the progress bar
        tqdm.pandas()

        # Apply function to each row of df
        df_gq.progress_apply(
            self.gen_files,
            axis=1,
            keys=keys,
        )

        # Now merge the generated XML files
        self.merge_xml(Path(self.templatefile).stem)

        print("")
        print("*** genmq has finished ***")
        print(
            "Execution for %d questions generated in %2.0f sec"
            % (len(df_gq.index), time.time() - t)
        )

        pass

    def remove_readonly(self, func, path, excinfo):
        """Attempts to remove a read-only file by changing the permissions"""
        os.chmod(path, stat.S_IWRITE)
        func(path)

    def make_template(self, texfile):
        """
        Creates the jinja2 template using a redefined template structure that
        plays nicely with LaTeX
        https://web.archive.org/web/20121024021221/http://e6h.de/post/11/

        Parameters
        ----------
        texfile : string
            The template LaTeX file containing jinja template variables.

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

    def generic(self, csvfile):
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

    def gen_files(self, values, keys):
        """
        Drives the rendering and compilation process for each row, and
        cleans up the files afterwards.

        Parameters
        ----------
        values : tuple of string
            Contains row of data: for student's: Moodle ID, Full Name, Student ID.
        keys : tuple of string
            Contains the field names of the data (i.e. worksheet column names)

        Returns
        -------
        None.

        """

        # Change method of assigning tmpfile names
        tmpfile = next(tempfile._get_candidate_names())

        # Create tex file
        self.render_file(values, keys, self.jinja_template, tmpfile)

        try:
            self.compile_files(tmpfile)

        finally:
            if self.delete_temps:
                for f in glob.glob(tmpfile + ".*"):
                    # Notice that here we want to retain the xml file and pdf for now
                    if not f == (tmpfile + ".xml"):
                        os.remove(f)
                path = "comment.cut"
                if os.path.exists(path):
                    os.remove(path)
                path = "pythontex-files-" + tmpfile
                if os.path.exists(path):
                    shutil.rmtree(path, onerror=self.remove_readonly)

    def compile_files(self, tmpfile):
        """
        Generates the quiz question document for a student

        Parameters
        ----------
        tmpfile : string
            Name of the temporary files.

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

        output = subprocess.run(cmd_pdflatex, shell=True, capture_output=True)
        if self.logfile:
            with open("genmq.log", "wb") as outfile:
                outfile.write(output.stdout)

        if self.pythontex:
            output = subprocess.run(cmd_pythontex, shell=True, capture_output=True)
            if self.logfile:
                with open("gq_pythontex.log", "wb") as outfile:
                    outfile.write(output.stdout)
            output = subprocess.run(cmd_pdflatex, shell=True, capture_output=True)
            if self.logfile:
                with open("gq_post_pythontex.log", "wb") as outfile:
                    outfile.write(output.stdout)

        self.tempxmlfiles.append(tmpfile + "-moodle.xml")

    def render_file(self, values, keys, template, tmpfile):
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
        p = re.compile(r"(^\\usepackage\S+)draft(\S+{moodle}$)", re.MULTILINE)
        document = p.sub(r"\1\2", document)
        # In case of empty options remaining
        document = document.replace(r"\usepackage[]{moodle}", r"\usepackage{moodle}")

        # write document
        with open(tmpfile + ".tex", "w", encoding="utf-8") as outfile:
            outfile.write(document)

    def merge_xml(self, stem):
        """
        Merges all the Moodle quiz xml files in the folder into one, saves the
        merged file, and deletes the temporary files.
        """

        # Parse the created XML files
        xml_files = self.tempxmlfiles
        roots = [ET.parse(f).getroot() for f in xml_files]
        base = roots[0]
        for r in roots[1:]:
            for el in r:
                if el.tag == "question" and el.attrib["type"] != "category":
                    base.append(el)

        base_xml = ET.ElementTree(base)
        base_xml.write(f"{stem}.xml", encoding="utf-8", xml_declaration=True)

        if self.delete_temps:
            # Now delete the xml files except for the new one
            # Note: will delete XML files already in the folder.
            for f in xml_files:
                os.remove(f)

        pass

    def clean_xml_files(self):
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
            if self.warn:
                delete = confirm_prompt(f"Delete {f}?")
            if delete:
                os.remove(f)


class Splitter:
    """
    A class to split a Moodle XML file into chunks
    """

    def __init__(self, xmlfile, maxfilesize):
        """
        Initialize the file splitter params
        """
        self.xmlfile = Path(xmlfile)
        self.maxfilesize = maxfilesize * 2 ** 20  # MB to bytes: 2^20 = 1 MB

    def split_xml_file(self):
        filesize = self.xmlfile.stat().st_size
        n_files = math.ceil(filesize / self.maxfilesize) + 1
        print(f"Writing {n_files} files")

        root = ET.parse(self.xmlfile).getroot()
        q_list = []
        for q in tqdm(root.findall("question"), desc="Parsing XML file"):
            if q.attrib["type"] != "category":
                q_list.append(q)
                root.remove(q)
        total_no_questions = len(q_list)
        q_per_file = math.floor(total_no_questions / n_files)
        print(f"Approx. no. of questions per file: {q_per_file}")

        working_root = copy.deepcopy(root)
        qidx = 0
        fidx = 0
        for q in tqdm(q_list, desc="Creating XML files"):
            working_root.append(q)
            qidx += 1
            if (qidx > q_per_file) or (fidx == n_files - 1):
                fidx += 1
                self.write_xml_file(
                    working_root, f"{self.xmlfile.name}-{fidx}.xml", fidx, qidx
                )
                working_root = copy.deepcopy(root)
                qidx = 0
        self.write_xml_file(working_root, f"{self.xmlfile.name}-{fidx}.xml", fidx, qidx)

    def write_xml_file(self, tree, fname, fidx, qidx):
        # print(f"Writing file {fidx} with {qidx+1} questions")
        base_xml = ET.ElementTree(tree)
        base_xml.write(fname, encoding="utf-8", xml_declaration=True)


def cli():
    """
    Command Line Interface for running as script or as command
    """

    normalmode = True
    if ("-s" or "--splitxml") in sys.argv:
        normalmode = False

    parser = argparse.ArgumentParser(
        description="Generate XML file for import as a Moodle Quiz, \
         using a LaTeX template and input csv"
    )

    normalmodeargs = parser.add_argument_group("Normal mode arguments")
    normalmodeargs.add_argument(
        "-t",
        "--template",
        help="LaTeX Template File with certain commands\
                                  for jinja2 based on Moodle.sty package",
        required=normalmode,
    )

    normalmodeargs.add_argument(
        "-c",
        "--csvfile",
        help="CSV file containing the named variables for the jinja2 template",
        required=normalmode,
    )

    normalmodeargs.add_argument(
        "-d",
        "--delete_temps",
        help="Do not delete temporary files",
        default=True,
        action="store_false",
    )

    normalmodeargs.add_argument(
        "-n",
        "--number",
        help="Compile the first n questions in the database",
        type=int,
    )

    normalmodeargs.add_argument(
        "-p",
        "--pythontex",
        help="Execute compilation twice if pythontex code included in file",
        default=False,
        action="store_false",
    )

    normalmodeargs.add_argument(
        "-w",
        "--warn",
        help="Warn before overwriting a previous genmq-moodle.xml file",
        default=True,
        action="store_false",
    )

    normalmodeargs.add_argument(
        "-l",
        "--log",
        help="Log the LaTeX output to file",
        default=False,
        action="store_true",
    )

    splitmodeargs = parser.add_argument_group("Split XML file mode required arguments")
    splitmodeargs.add_argument(
        "-s",
        "--splitxml",
        help="Use: as genmq --splitxml [file] -z [x] \
                Split the XML [file] into chunks smaller than [x] MB",
        type=str,
    )

    splitmodeargs.add_argument(
        "-z",
        "--maxfilesize",
        help="The maximum file size (MB) of the XML chunks (default = 20 MB)",
        default=20,
        type=int,
    )

    args = parser.parse_args()

    if normalmode:
        gmq = GenMoodleQuiz(args)
        gmq.run()
    else:
        xml_splitter = Splitter(args.splitxml, args.maxfilesize)
        xml_splitter.split_xml_file()


if __name__ == "__main__":
    cli()
