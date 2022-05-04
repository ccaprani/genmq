# genmq
A Moodle quiz generator using LaTeX and the `moodle.sty` package with jinja2 templates

*Generates Individualized Moodle Quizzes based on a LaTeX Template*

**Author:** Colin Caprani,
[colin.caprani@monash.edu](mailto://colin.caprani@monash.edu)

## Overview
`genmq` is a python package that performs mail-merge like functionality to generate a Moodle quiz XML file for bulk upload. It uses a template latex file based on the [`moodle.sty`](https://framagit.org/mattgk/moodle) package, and populates placeholder variables with entries from a prepared csv file to generate many variants of the template question. It can include the answers, precision, and feedback; all as described in the documentation for the `moodle.sty` package.

`genmq` can also split larger Moodle XML files into multiple files to facilitate uploading when there are file size limits.

## Installation

`genmq` installs as a command into your system.

### Using pip

```python
pip install genmq
```

### For development
Clone or download this repository to a local directory. Open a terminal in that directory (where this README will be found) and run:

```python
pip install -e .
```


## Typical Usage

For generating quizzes:

```bash
genmq -t [template].tex -c [database].csv
```

For splitting an existing large XML file:
```bash
genmq -s [moodle_quiz].xml
```

To see all arguments, run `genmq --help`.

