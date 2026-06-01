import datetime as dt
import re
from pathlib import Path

from NIHData.cache import env as CacheHandler
from NIHData.errors import EnvFileDoesNotExist, EnvVarDoesNotExist, CacheDoesNotExist, NoValidSearchLocations

year_search = re.compile(r"(?P<year>\d{4})")
nih_exporter_file_regex = re.compile(r"^RePORTER_PRJ_C_FY(?P<year>\d{4})(?P<filetype>\.[^0-9.]+)$", re.I)
"""Name of the typical file target. The csv file within the zip also follows this naming convention."""

NIH_DATA_CACHE = ".nih_data_cache"
NIH_CACHE_ENV_VAR_NAME = 'NIH_DATA_CACHE_DIR'
NIH_CACHE_ENV_FILE_NAME = f".nih_data_cache.env"


def find_nih_data(check_locations: str | Path | list[str | Path] | None = None, suppress_warnings: bool = False) -> \
list[Path]:
    """
    Assumes that downloaded files follow the typical NIH data file name structure.
    ``RePORTER_PRJ_C_FY{year}``

    :parameter check_locations: The locations to search for NIH data .zip files.
    :parameter suppress_warnings: Suppresses warning messages for specific searches.
    """
    match check_locations:
        case str() | Path():
            check_locations = [Path(check_locations)]
        case list():
            check_locations = [Path(p) for p in check_locations]
        case _:
            check_locations = [
                *[Path.home() / d for d in ('Downloads', "downloads", 'Download', 'download')]
            ]

    valid_to_search: list[Path] = []
    seen = set()

    for p in check_locations:
        if not p.exists():
            continue
        stat = p.stat()
        device_id = stat.st_dev
        file_inode_or_index = stat.st_ino
        key = (device_id, file_inode_or_index)
        if key not in seen:
            seen.add(key)
            valid_to_search.append(p)

    try:
        cache_dir = CacheHandler.get_cache_path()
        valid_to_search.append(cache_dir)
    except CacheDoesNotExist | EnvFileDoesNotExist | EnvVarDoesNotExist as e:
        cache_dir = None
        if not suppress_warnings:
            print(e)

    if not valid_to_search:
        raise NoValidSearchLocations(f"Tried the following paths, but none were valid: {", ".join(check_locations)}")
    elif len(valid_to_search) == 1:
        search_start_message = f"Searching `{check_locations[0]}` for NIH exporter files."
    else:
        search_start_message = (
            f"Searching the following directories for NIH exporter files: "
            f"\n{"\n".join(f"{i}.) `{p}`" for i, p in enumerate(valid_to_search, start=1))} "
        )

    print(search_start_message)

    files_found_by_path: dict[Path, list[Path]] = dict()
    files_found_by_year: dict[str, list[Path]] = dict()

    for p in valid_to_search:
        p: Path
        for file in p.iterdir():
            if not all((file.exists(), (file.is_file(), file.stat().st_size > 0))):
                continue
            file_match = nih_exporter_file_regex.search(file.name)
            if file_match and file_match['filetype'] == '.zip':
                files_found_by_path.setdefault(p, []).append(file)
                files_found_by_year.setdefault(file_match['year'], []).append(file)

        if files_found_by_path.get(p, None):
            print(f"Found {files_found_by_path[p]} in {p}.")
        else:
            print(f"Found no files in {p}")

    years: list[str] = sorted(y for y in files_found_by_year.keys())
    year_gaps = []

    for i, year in enumerate(years):
        if i == len(years) - 1:
            continue

        next_year = years[i + 1]
        missing_years = (int(next_year) - int(year)) - 1

        if missing_years != 0:
            missing_year_nums = [f"{int(year) + y + 1}" for y in range(missing_years)]
            str_prefix = len(year_gaps) + 1
            year_gaps.append(
                f"    {str_prefix}.) Missing years {", ".join(missing_year_nums)} between {year} and {next_year}.")

    print(f"Found data for years: {", ".join(years)}.")

    if year_gaps:
        print(f"Noted the following gaps in existing data: ")
        print("\n".join(year_gaps))

    current_year_post_mil = dt.datetime.now().year - 2000
    # Assume that last year's data is published roughly around start of the current year
    # Or at least flag that the user should check

    years_that_can_be_processed = {2000 + y for y in range(current_year_post_mil)}
    # NIH data format changed in year 2000; there is very little meaningful data
    # prior to this, and 25+ years is enough for the vast majority of analyses.

    missing = sorted(years_that_can_be_processed - {int(y) for y in years})
    if missing:
        print(
            f"Files from 2000 onwards can be processed. "
            f"Missing zip files for years: {", ".join(str(y) for y in missing)}. "
            f"Go to https://reporter.nih.gov/exporter to download missing files."
        )
    else:
        print(f"Found files for 2000 - 20{current_year_post_mil - 1}")

    files_found: list[Path] = list()
    for year, zip_files in files_found_by_year.items():
        match len(zip_files):
            case 0:
                continue
            case 1:
                files_found.append(zip_files[0])
            case _:
                if cache_dir and cache_dir.exists() and [f for f in zip_files if f.root == cache_dir.root][:]:
                    files_found.append([f for f in zip_files if f.root == cache_dir.root][:][0])
                else:
                    # we know here that zip files exist as the guard is the first case
                    files_found.append(zip_files[0])

    return sorted(files_found)


def build_nih_data_cache(
        cache_path: str | Path | None = None,
        file_locations: str | Path | list[str | Path] | None = None,
        overwrite_cache: bool = True,
        delete_originals: bool = False) -> list[Path]:
    """
    Defaults:
        - If ``cache_path`` is ``None``, then use the package default (Path.home() / .nih_data_cache).
        - If ``file_locations`` is ``None``, then search the "downloads" directory in the home folder.
        - Overwrites files in cache using files found in provided paths.
        - Retains original zip files in their directories.

    :returns: List of paths pointing to cached files.
    """
    cache_path = CacheHandler.create_cache_directory(cache_path)
    nih_data_files = find_nih_data(file_locations)
    files_pulled_from = {f.root for f in nih_data_files}
    files_pulled_from.discard(cache_path)  # Discard instead of remove so we're not throwing an error.

    existing_cache = {f.name for f in cache_path.iterdir() if nih_exporter_file_regex.search(f.name)}
    cached_file_paths: list[Path] = []

    for file in nih_data_files:
        if file.root == cache_path:
            # Skip files already found in the cache.
            continue
        elif (file.name in existing_cache and overwrite_cache) or file.name not in existing_cache:
            print(f"Copying {file.name} to {cache_path}")
            cached_path = file.copy_into(cache_path, preserve_metadata=True)
            cached_file_paths.append(cached_path)
        elif file.name in existing_cache and not overwrite_cache:
            print(f"{file.name} is already in cache. Skipping...")
            continue

        if delete_originals:
            # Files from the cache are already skipped with the first guard, so this doesn't risk unlinking already
            # cached files.
            to_delete.append(file)

    completion_message = [
        f"Copied {len(cached_file_paths) if cached_file_paths else "no"} files to cache. ",
        f"Total MB copied: {_calculate_total_file_size(cached_file_paths)} MB",
    ]
    if to_delete:
        completion_message.append(
            f"Deleted {len(to_delete)} files from {", ".join({p.parent.name for p in to_delete})}. "
            f"Total MB cleared: {_calculate_total_file_size(to_delete)}"
        )
        for p in to_delete:
            p.unlink()

    print("\n".join(completion_message))

    return cached_file_paths


if __name__ == "__main__":
    build_nih_data_cache()




