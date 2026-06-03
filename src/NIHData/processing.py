import polars as pl

from NIHData.cache.manager import get_csv_data
from NIHData.columns import NIHDataColumn
from NIHData.schemas import BASE_NIH_SCHEMA

col = NIHDataColumn


def detect_schema_drift(years: list[str] | None = None):
    csv_data = get_csv_data(years)

    schemas = []
    for block in csv_data:
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


def _resolve_schema(df: pl.DataFrame) -> pl.DataFrame:
    """Right now, only renames CFDA_CODE due to drift in FY2024 onwards."""
    s = df.schema

    if "CFDA_CODE" in s.keys():
        df = df.rename({"CFDA_CODE": "ASSISTANCE_LISTING_NUMBER"})

    return df


def build_dataframe_from_csv_data(years: list[str] | None = None) -> pl.DataFrame:
    csv_data = get_csv_data(years)
    dataframes: list[pl.DataFrame] = []

    for block in csv_data:
        df = pl.read_csv(block, schema=BASE_NIH_SCHEMA)

        dataframes.append(df)

    df = pl.concat(dataframes, how="vertical")



    org_cols = [
        col.ORG_NAME, col.ORG_COUNTRY, col.ORG_IPF_CODE, col.ED_INST_TYPE,
        col.ORG_CITY, col.ORG_STATE,  col.ORG_DUNS, col.ORG_FIPS
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
    
    return df

def _main():
    build_dataframe_from_csv_data(years=["2024"])

if __name__ == '__main__':
    _main()
