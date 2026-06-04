from pathlib import Path

import polars as pl

from NIHData.cache.manager import CacheResult
from NIHData.columns import NIHDataColumn
from NIHData.schemas import BASE_NIH_SCHEMA

col = NIHDataColumn


def detect_schema_drift(years: list[str] | None = None):
    result = CacheResult(years)

    schemas = []
    for block in result.yield_csv():
        df = pl.read_csv(block, infer_schema=True, infer_schema_length=100000)
        schemas.append(df.schema)

    diffs = []
    for i, schema in enumerate(schemas):
        for i2, schema2 in enumerate(schemas):
            if i == i2:
                continue
            if diff := schema2.keys() - schema.keys():
                diffs.append((diff, i2, i))
    if diffs:
        for d in diffs:
            diff, i, i2 = d
            print(f"Found diff between schema at {i2} and {i}; diff == {sorted(diff)}")
    else:
        print("Schema names from all files are in sync.")


# Known column drift: raw-CSV column name -> canonical schema name.
_DRIFT_RENAMES = {"CFDA_CODE": "ASSISTANCE_LISTING_NUMBER"}


def _resolve_schema(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Rename drifted columns (e.g. CFDA_CODE, present in pre-FY2024 files) to canonical names."""
    names = lf.collect_schema().names()
    renames = {src: dst for src, dst in _DRIFT_RENAMES.items() if src in names}
    if renames:
        lf = lf.rename(renames)

    return lf


def _scan_csv_to_canonical(csv_path: Path) -> pl.LazyFrame:
    """
    Scan one extracted CSV, resolve known column drift, then enforce the canonical schema.

    ``schema_overrides`` applies the target dtypes by name to whichever columns are present.
    Drift-source columns are forced to ``String`` so type inference can't mis-type them
    (e.g. ``CFDA_CODE`` values like ``"94.006"`` inferred as ``i64``); they are renamed onto
    the canonical name, column order, and dtypes before the final ``select``.
    """
    overrides = {**BASE_NIH_SCHEMA, **{src: pl.String for src in _DRIFT_RENAMES}}
    lf = pl.scan_csv(csv_path, schema_overrides=overrides)
    lf = _resolve_schema(lf)
    return lf.select(
        [pl.col(name).cast(dtype) for name, dtype in BASE_NIH_SCHEMA.items()]
    )


def build_dataframe_from_csv_data(years: list[str] | None = None) -> pl.DataFrame:
    """
    Build an in-memory DataFrame directly from cached CSVs (bypassing parquet).

    If no ``years`` are provided, then uses data for all years in cache. Each file is
    collected eagerly because the extracted CSV temp file only lives for one generator step.
    """
    csv_data = CacheResult(years)
    dataframes: list[pl.DataFrame] = [
        _scan_csv_to_canonical(csv_path).collect()
        for _, csv_path in csv_data.yield_csv_files()
    ]

    if not dataframes:
        raise FileNotFoundError("No cached NIH zip files found to build a DataFrame.")

    return pl.concat(dataframes, how="vertical")


def write_parquet_to_cache(years: list[str] | None = None) -> list[Path]:
    """Write one ``{year}.parquet`` per cached year, streaming via ``sink_parquet``."""
    result = CacheResult(years)
    written: list[Path] = []

    for year, csv_path in result.yield_csv_files():
        parquet_path = result.get_parquet_path_for_year(year)
        if parquet_path.exists():
            print(f"Overwriting file at {parquet_path}...")
        else:
            print(f"Writing {parquet_path.name} to cache.")

        _scan_csv_to_canonical(csv_path).sink_parquet(parquet_path)
        written.append(parquet_path)

    return written


def get_dataframe(years: list[str] | None = None) -> pl.DataFrame:
    """Return cached data as a DataFrame, building any missing per-year parquet first."""
    cache = CacheResult(years)
    missing = [
        y for y in cache.years_found
        if not cache.get_parquet_path_for_year(y).exists()
    ]
    if missing:
        print(f"Building parquet for years: {", ".join(missing)}")
        write_parquet_to_cache(missing)

    return cache.get_parquet_df()


def get_org_dataframe(years: list[str] | None = None):
    df = get_dataframe(years)

    org_cols = [
        col.ORG_NAME, col.ORG_COUNTRY, col.ORG_IPF_CODE, col.ED_INST_TYPE,
        col.ORG_CITY, col.ORG_STATE, col.ORG_DUNS, col.ORG_FIPS
    ]

    funding_cols = [
        col.DIRECT_COST_AMT, col.INDIRECT_COST_AMT, col.TOTAL_COST, col.TOTAL_COST_SUB_PROJECT
    ]

    funding_by_org_and_country = (
        df.select(*org_cols, *funding_cols)
        .filter(col.ORG_FIPS != "US")
        .group_by([col.ORG_NAME, col.ORG_COUNTRY])
        .agg(
            total_cost=col.TOTAL_COST.sum(),
            total_cost_with_sub=(col.TOTAL_COST.fill_null(0) + col.TOTAL_COST_SUB_PROJECT.fill_null(0)).sum(),
            num_projects=pl.len(),
        )
        .sort("total_cost_with_sub", descending=True)
    )

    funding_by_country = (
        funding_by_org_and_country
        .group_by(col.ORG_COUNTRY)
        .agg(
            country=col.ORG_COUNTRY.first(),
            total_cost=pl.col("total_cost").sum(),
            total_cost_with_sub=pl.col("total_cost_with_sub").sum(),
            num_projects=pl.len(),
        )
        .sort("total_cost_with_sub", descending=True)
    )

    print(funding_by_org_and_country)
    print(funding_by_country)

    return


def _main():
    write_parquet_to_cache()


if __name__ == '__main__':
    _main()
