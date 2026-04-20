from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version("aidevkit")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
