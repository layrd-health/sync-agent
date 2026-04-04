"""Layrd Document Sync Agent."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("layrd-sync-agent")
except PackageNotFoundError:
    __version__ = "0.6.6"
