from pathlib import Path
from NIHData.errors import CacheDoesNotExist, EnvFileDoesNotExist, EnvVarDoesNotExist

NIH_CACHE_ENV_VAR_NAME = 'NIH_DATA_CACHE_DIR'
NIH_CACHE_ENV_FILE_NAME = f".nih_data_cache.env"
NIH_CACHE_ENV_FILE_PATH = Path.home() / NIH_CACHE_ENV_FILE_NAME


def _read_env_file():
    if not NIH_CACHE_ENV_FILE_PATH.exists():
        raise EnvFileDoesNotExist(
            "Could not find env file that points to cache directory. Create the environment file first."
        )

    with open(NIH_CACHE_ENV_FILE_PATH, 'r', encoding='utf-8') as envfile:
        data = [l for l in envfile.readlines() if not l.startswith("#")]

    mapping = {x[0]: x[1] for x in [p.strip().split('=') for p in data]}
    return mapping


def get_cache_path():
    """
    Reads environment variable and returns the path to the cache directory, if it exists.

    :return: Path to the cache directory.
    :raises EnvVarDoesNotExist: Raised if the environment variable is not found in the .env mapping.
    :raises EnvFileDoesNotExist: Raised if the environment variable file has not been created yet.
    """
    try:
        env_data = _read_env_file()
        if cache_path_str := env_data.get(NIH_CACHE_ENV_VAR_NAME, None):
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


def create_cache_directory(path: str | Path | None = None):
    """
    Defaults to 'Path.home() / .nih_data_cache' if no direct path is provided to generate the cache.

    Also checks to see if an .nih_env_cache.env file exists in the Path.home() dir; if not, creates one.
    """

    nih_data_cache_path = Path(path) if path else Path.home() / '.nih_data_cache'

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


def delete_cache_directory():
    print("Deleting files in cache directory, and environment variable.")
    mapping = _read_env_file()
    if NIH_CACHE_ENV_VAR_NAME not in mapping:
        raise EnvVarDoesNotExist(f"{NIH_CACHE_ENV_VAR_NAME} env variable not present in environment mapping.")

    nih_data_cache_path = Path(mapping[NIH_CACHE_ENV_VAR_NAME])
    if nih_data_cache_path == Path.home():
        raise ValueError("Error: this is attempting to clear files from your Home directory. "
                         "This is a universal short circuit; please check your environment setup before "
                         "proceeding.")

    for file in nih_data_cache_path.iterdir():
        print(f"[FILE] Deleting {file}")
        file.unlink()

    print(f"[DIRECTORY] Deleting {nih_data_cache_path}")
    nih_data_cache_path.rmdir()
    print(f"[ENV_FILE] Deleting {NIH_CACHE_ENV_FILE_PATH}")
    NIH_CACHE_ENV_FILE_PATH.unlink()

    print("[VALIDATION] Running checks...")

    checks = enumerate((
        (not nih_data_cache_path.exists(),
         "NIH data cache successfully deleted.",
         "NIH data cache not deleted. Check environment variable."
         ),
        (not NIH_CACHE_ENV_FILE_PATH.exists(),
         "NIH environment variable successfully deleted.",
         f"NIH environment variable not deleted. Please review what is located at {NIH_CACHE_ENV_FILE_PATH}."
         )
    ), start=1)

    errors = []

    for n, check in checks:
        valid, success_message, error = check
        if valid:
            print(f"[{n}] {success_message}")
        else:
            errors.append(error)

    if errors:
        raise ValueError(errors)

    print("[SUCCESS] Cache successfully deleted!")
