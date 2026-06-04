import csv
import datetime as dt
import io
import re
import tempfile
import zipfile
from collections.abc import Generator
from pathlib import Path

import polars as pl

from NIHData.cache.env import (
    create_cache_directory, get_cache_path,
)
from NIHData.domain.types import NIHExporterRow, NIHExporterRowHeader
from NIHData.domain.errors import (
    EnvFileDoesNotExist, EnvVarDoesNotExist,
    CacheDoesNotExist, NoValidSearchLocations,
    NoCsvInZipFile,
)

nih_exporter_file_regex = re.compile(r"^RePORTER_PRJ_C_FY(?P<year>\d{4})(?P<filetype>\.[^0-9.]+)$", re.I)
"""Name of the typical file target. The csv file within the zip also follows this naming convention."""

# Assume that last year's data is published roughly around start of the current year
# Or at least flag that the user should check
current_year_post_mil = dt.datetime.now().year - 2000

# NIH data format changed in year 2000; there is very little meaningful data
# prior to this, and 25+ years is enough for the vast majority of analyses.
years_that_can_be_processed = {2000 + y for y in range(current_year_post_mil)}


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
        cache_dir = get_cache_path()
        valid_to_search.append(cache_dir)
    except (CacheDoesNotExist, EnvFileDoesNotExist, EnvVarDoesNotExist) as e:
        cache_dir = None
        if not suppress_warnings:
            print(e)

    if not valid_to_search:
        raise NoValidSearchLocations(f"Tried the following paths, but none were valid: "
                                     f"{", ".join(str(l) for l in check_locations)}")
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
            if not all((file.exists(), file.is_file(), file.stat().st_size > 0)):
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
        print("")

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
                cached_dupes = [f for f in zip_files if f.parent == cache_dir] if cache_dir else []
                if cache_dir and cache_dir.exists() and cached_dupes:
                    files_found.append(cached_dupes[0])
                else:
                    # we know here that zip files exist as the guard is the first case
                    files_found.append(zip_files[0])

    return sorted(files_found)


def _calculate_total_file_size(files: list[Path]):
    """:returns: Total size of files in provided path list (in MB)."""
    return sum(f.stat().st_size for f in files) / (1000 * 1000)


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
    cache_path = create_cache_directory(cache_path)
    nih_data_files = find_nih_data(file_locations)
    files_pulled_from = {f.parent for f in nih_data_files}
    files_pulled_from.discard(cache_path)  # Discard instead of remove so we're not throwing an error.

    existing_cache = {f.name for f in cache_path.iterdir() if nih_exporter_file_regex.search(f.name)}
    print(f"Existing files in cache: {existing_cache}")
    cached_file_paths: list[Path] = []
    to_delete: list[Path] = []

    for file in nih_data_files:
        if file.parent == cache_path:
            print(f"{file} is already in cache. Skipping copy...")
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


class CacheConfig:
    processable_years: set[int] = years_that_can_be_processed
    current_year_num: int = current_year_post_mil
    min_year_processable: int = min(processable_years)
    max_year_processable: int = max(processable_years)

    def __init__(self, years: list | None):
        self.years_requested: list[int] = (
            sorted(int(y) for y in years) if years
            else sorted(years_that_can_be_processed)
        )
        self.min_year_requested = min(self.years_requested)
        self.max_year_requested = max(self.years_requested)
        self.gaps = self._determine_gaps()

    def _determine_gaps(self) -> list[int]:
        years = self.years_requested  # already a sorted list[int]
        gaps: list[int] = []
        for i, year in enumerate(years):
            if i == 0:
                continue
            prior = years[i - 1]
            if year - prior > 1:
                gaps.extend(range(prior + 1, year))
        return gaps


class CacheResult:
    """
    Yields generator of csv data for each zip file found. Min year/max year is maintained as state.
    """
    def __init__(self, years: list | None):
        self.config = CacheConfig(years)

        self._zip_by_year: dict[str, Path] = {}

        for p in get_cache_path().iterdir():
            result = nih_exporter_file_regex.search(p.name)
            if result and result['filetype'] == '.zip':
                file_year = result['year']
                if (not years) or (file_year in years):
                    self._zip_by_year[file_year] = p

        self.years_found: list[str] = sorted(self._zip_by_year)
        self.zip_files: list[Path] = [self._zip_by_year[y] for y in self.years_found]
        self.min_year = min(self.years_found)
        self.max_year = max(self.years_found)

    def __repr__(self):
        return str(self)

    def __str__(self):
        return f"CacheResult(Years=[{", ".join(self.years_found)}])"

    def yield_csv(self):
        print(f"Loading {len(self.zip_files)} zip files for processing.")
        for zip_file in self.zip_files:
            with (zipfile.ZipFile(zip_file, mode='r') as zf):
                candidates = [
                    info for info in zf.infolist()
                    if nih_exporter_file_regex.search(info.filename)
                       and '.csv' in info.filename
                ]
                if candidates:
                    target = candidates[0]
                    yield io.StringIO(zf.read(target).decode('utf-8'))
                else:
                    raise NoCsvInZipFile(f"Could not find .csv file in {zip_file}.")

    def yield_csv_files(self) -> Generator[tuple[str, Path], None, None]:
        """
        Extract each zip's CSV to a temporary file and yield ``(year, csv_path)``.

        Unlike :meth:`yield_csv`, this does not read the whole CSV into memory, so the
        consumer can hand the path to ``pl.scan_csv`` and stream. Each temp file lives only
        until the generator advances to the next zip, so the consumer must finish using the
        path (e.g. ``sink_parquet`` / ``collect``) before requesting the next item.
        """
        print(f"Loading {len(self.zip_files)} zip files for processing.")
        for year in self.years_found:
            zip_file = self._zip_by_year[year]
            with zipfile.ZipFile(zip_file, mode='r') as zf:
                candidates = [
                    info for info in zf.infolist()
                    if nih_exporter_file_regex.search(info.filename)
                       and '.csv' in info.filename
                ]
                if not candidates:
                    raise NoCsvInZipFile(f"Could not find .csv file in {zip_file}.")
                target = candidates[0]
                with tempfile.TemporaryDirectory() as tmpdir:
                    zf.extract(target, tmpdir)
                    yield year, Path(tmpdir) / target.filename

    def as_dict_rows(self) -> Generator[NIHExporterRow, None, None]:
        for data in self.yield_csv():
            reader = csv.DictReader(data, fieldnames=NIHExporterRowHeader)
            for row in reader:
                yield row
                
    def get_parquet_path_for_year(self, year: str | int) -> Path:
        """One parquet per year, e.g. ``2020.parquet`` — avoids misleading range names."""
        return get_cache_path() / f"{year}.parquet"

    def existing_parquet_paths(self) -> list[Path]:
        """Per-year parquet paths (for the requested years) that already exist on disk."""
        return [
            p for y in self.years_found
            if (p := self.get_parquet_path_for_year(y)).exists()
        ]

    def get_parquet_lf(self) -> pl.LazyFrame:
        paths = self.existing_parquet_paths()
        if not paths:
            raise FileNotFoundError(
                "No per-year parquet files exist yet. Parse csv and write to the cache first."
            )
        return pl.scan_parquet(paths)

    def get_parquet_df(self) -> pl.DataFrame:
        return self.get_parquet_lf().collect()



def get_cache_result(years: list[str] | None):
    """Factory for CacheResult class."""
    return CacheResult(years)
