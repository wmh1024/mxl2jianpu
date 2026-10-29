"""mxl2jianpu — turn an OMR'd MusicXML file into a numbered-notation PDF.

Run ``mxl2jianpu --help`` (or ``python -m mxl2jp.cli --help``) for the commands.
"""
from . import musicxml, diagnose, repair, jianpu, compare, render, pipeline

__version__ = '1.0.0'

__all__ = ['musicxml', 'diagnose', 'repair', 'jianpu',
           'compare', 'render', 'pipeline']
