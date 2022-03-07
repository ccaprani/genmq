# genquiz
A Moodle quiz generator using LaTeX and the `moodle.sty` package with jinja2 templates

*Generates Individualized Moodle Quizzes based on a LaTeX Template*

**Author:** Colin Caprani,
[colin.caprani@monash.edu](mailto://colin.caprani@monash.edu)

## Overview
`genquiz` is a wrapper script that performs mail-merge like functionality to generate a Moodle quiz XML file for bulk upload. It uses a template latex file based on the [`moodle.sty`](https://framagit.org/mattgk/moodle) package, and populates placeholder variables with entries from a prepared csv file to generate many variants of the template question. It can include the answers, precision, and feedback; all as described in the documentation for the `moodle.sty` package.

## Usage
When located in a different directory, that is added to PYTHONPATH:

```python
python -m genquiz [template].tex [database].csv  -s
```

otherwise, when in the same directory: 

```python
python genquiz.py [template].tex [database].csv  -s
```

-s is an indicator to say that there is no pythontex variables in the template.

## Warning
`genquiz` is functional, but the code needs to be cleaned up and documentation produced.
