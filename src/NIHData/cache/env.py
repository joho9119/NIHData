from pathlib import Path
from NIHData.errors import CacheDoesNotExist, EnvFileDoesNotExist, EnvVarDoesNotExist

NIH_CACHE_ENV_VAR_NAME = 'NIH_DATA_CACHE_DIR'
NIH_CACHE_ENV_FILE_NAME = ".nih_data_cache.env"
NIH_CACHE_ENV_FILE_PATH = Path.home() / NIH_CACHE_ENV_FILE_NAME
NIH_CACHE_DEFAULT_PATH = Path.home() / ".nih_data_cache"


def _read_env_file():
    if not NIH_CACHE_ENV_FILE_PATH.exists():
        raise EnvFileDoesNotExist(
            "Could not find env file that points to cache directory. Create the environment file first."
        )

    with open(NIH_CACHE_ENV_FILE_PATH, 'r', encoding='utf-8') as envfile:
        data = [l for l in envfile.readlines() if not l.startswith("#")]

    mapping = {x[0]: x[1] for x in [p.strip().split('=') for p in data]}
    return mapping


def _get_cache_path_string() -> str | None:
    """
    Safely returns the path to the cache (as a string) without raising.
    """
    try:
        env_data = _read_env_file()
        return env_data.get(NIH_CACHE_ENV_VAR_NAME, None)
    except EnvFileDoesNotExist as e:
        print(e)
        return None


def setup_env_file(cache_path: Path) -> None:
    print(f"Setting {NIH_CACHE_ENV_VAR_NAME}={cache_path}.")
    lines = (
        f"# This file holds the environment variable for the NIH Data Cache.",
        f"{NIH_CACHE_ENV_VAR_NAME}={cache_path}"  # sets env var
    )
    with open(NIH_CACHE_ENV_FILE_PATH, mode='w', encoding='utf-8') as envfile:
        envfile.write("\n".join(lines))


def get_cache_path() -> Path:
    """
    Reads environment variable and returns the cache_path to the cache directory, if it exists.

    :return: Path to the cache directory.
    :raises EnvVarDoesNotExist: Raised if the environment variable is not found in the .env mapping.
    :raises EnvFileDoesNotExist: Raised if the environment variable file has not been created yet.
    """
    try:
        if cache_path_str := _get_cache_path_string():
            cache_path = Path(cache_path_str)
            if not cache_path.exists():
                raise CacheDoesNotExist("Cache directory does not exist.")
            return Path(cache_path)
        else:
            raise EnvVarDoesNotExist(
                "The environment variable does not exist for the cache directory. Run setup to create."
            )
    except EnvFileDoesNotExist as e:
        raise e


def create_cache_directory(cache_path: str | Path | None = None) -> Path:
    """
    Defaults to 'Path.home() / .nih_data_cache' if no direct cache_path is provided to generate the cache.

    Also checks to see if an .nih_env_cache.env file exists in the Path.home() dir; if not, creates one.
    """
    nih_data_cache_path = Path(cache_path) if cache_path else NIH_CACHE_DEFAULT_PATH

    if not nih_data_cache_path.exists():
        print(f"No cache directory found at {nih_data_cache_path}. Creating...")
        nih_data_cache_path.mkdir()

    if not NIH_CACHE_ENV_FILE_PATH.exists():
        print(f"No {NIH_CACHE_ENV_FILE_NAME} found in home directory. Creating...")
        NIH_CACHE_ENV_FILE_PATH.touch()

    print(f"Setting {NIH_CACHE_ENV_VAR_NAME} to {nih_data_cache_path}.")

    with open(NIH_CACHE_ENV_FILE_PATH, mode='w', encoding='utf-8') as envfile:
        envfile.writelines((
            f"# This file holds the environment variable for the NIH Data Cache.\n",
            f"{NIH_CACHE_ENV_VAR_NAME}={nih_data_cache_path}"
        ))

    return nih_data_cache_path


def delete_cache_directory() -> None:
    print("Deleting files in cache directory, and environment variable.")
    mapping = _read_env_file()
    if NIH_CACHE_ENV_VAR_NAME not in mapping:
        raise EnvVarDoesNotExist(f"{NIH_CACHE_ENV_VAR_NAME} env variable not present in environment mapping.")

    nih_data_cache_path = Path(mapping[NIH_CACHE_ENV_VAR_NAME])
    if nih_data_cache_path == Path.home():
        raise ValueError("Error: this is attempting to clear files from your Home directory. "
                         "This is a universal short circuit; please check your environment setup before "
                         "proceeding.")

    for n, file in enumerate(nih_data_cache_path.iterdir(), start=1):
        print(f"[FILE-{n}] Deleting {file} from cache")
        file.unlink()

    print(f"[DIRECTORY] Deleting {nih_data_cache_path}")
    nih_data_cache_path.rmdir()
    print("[SUCCESS] Cache successfully deleted.")

    if NIH_CACHE_ENV_FILE_PATH.exists():
        print(f"[ENV_FILE] Deleting {NIH_CACHE_ENV_FILE_PATH}")
        NIH_CACHE_ENV_FILE_PATH.unlink()
        print("[SUCCESS] Environment file successfully deleted.")
