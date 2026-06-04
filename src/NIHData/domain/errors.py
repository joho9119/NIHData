class CacheDoesNotExist(ValueError):
    """Raised when the cache directory has not been created yet."""


class EnvFileDoesNotExist(FileNotFoundError):
    """Raised when the file containing the package's environment variables has not been created yet."""


class EnvVarDoesNotExist(KeyError):
    """Raised when the environment variable has not been created yet."""


class NoValidSearchLocations(ValueError):
    """Raised when no paths are valid to search for files."""


class NoCsvInZipFile(FileNotFoundError):
    """Raised when no csv file is found in cached zip files."""


class InvalidNameIdOrder(ValueError):
    """Raised when the name and ID objects for a person on a project are out of order."""


class UnknownBooleanConversion(ValueError):
    """Raised when there is an unknown value in an ostensibly boolean field."""
