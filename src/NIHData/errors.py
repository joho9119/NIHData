class CacheDoesNotExist(ValueError):
    """Occurs when the cache directory has not been created yet."""


class EnvFileDoesNotExist(FileNotFoundError):
    """Occurs when the file containing the package's environment variables has not been created yet."""


class EnvVarDoesNotExist(KeyError):
    """Occurs when the environment variable has not been created yet."""


class NoValidSearchLocations(ValueError):
    """Occurs when no paths are valid to search for files."""
