"""Starter kit for the GAGNVÍST 2026 hackathon.

Answers questions in Icelandic or English from Statistics Iceland's tables: the
numbers come from the data files, the words from a language model.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("gagnvist")
except PackageNotFoundError:  # running from a source checkout without `pip install`
    __version__ = "0.0.0+local"
