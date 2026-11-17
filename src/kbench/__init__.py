"""Independent benchmark suite for karasu-slicer and other resin slicers."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("karasu-slicer-benchmark")
except PackageNotFoundError:  # A source tree that was never installed.
    __version__ = "0+unknown"
