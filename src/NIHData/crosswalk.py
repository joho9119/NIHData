"""DUNS -> UEI crosswalk sourced from the NIH RePORTER API.

The bulk ExPORTER project files expose ``ORG_DUNS`` but not the UEI (Unique Entity
Identifier) that federal grantees are identified by going forward. The RePORTER API,
by contrast, returns both ``org_duns`` and ``primary_uei`` per project.

Rather than paging every project (the API caps ``offset`` at ~15k per search), this
picks one representative project per distinct ``ORG_DUNS`` — the most recent fiscal
year, so the UEI reflects the current registration — and queries those ``appl_ids``
in batches. The result is a DUNS -> UEI map covering exactly the organizations in the
ExPORTER data, written to a committed parquet under the package.
"""
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import polars as pl

REPORTER_SEARCH_URL = "https://api.reporter.nih.gov/v2/projects/search"
_BATCH_SIZE = 500
_REQUEST_PAUSE_S = 1.0  # RePORTER asks callers to stay at/under 1 request per second
_TIMEOUT_S = 60
_MAX_RETRIES = 3

DATA_DIR = Path(__file__).parent / "data"
DUNS_UEI_MAP_PATH = DATA_DIR / "duns_uei_map.parquet"

_MAP_SCHEMA = {
    "duns": pl.String,
    "uei": pl.String,
    "org_name": pl.String,
    "org_ipf_code": pl.String,
    "api_primary_duns": pl.String,
    "n_ueis": pl.Int32,
}


def _representative_appl_ids(df: pl.DataFrame) -> pl.DataFrame:
    """One representative (latest-FY) ``APPLICATION_ID`` per distinct ``ORG_DUNS``."""
    return (
        df.lazy()
        .select("ORG_DUNS", "APPLICATION_ID", "FY")
        .drop_nulls("ORG_DUNS")
        .sort("FY")
        .group_by("ORG_DUNS", maintain_order=True)
        .agg(appl_id=pl.col("APPLICATION_ID").last())
        .rename({"ORG_DUNS": "duns"})
        .with_columns(appl_id=pl.col("appl_id").cast(pl.Int64))
        .drop_nulls("appl_id")
        .collect()
    )


def _fetch_org_by_appl_ids(appl_ids: list[int]) -> dict[int, dict]:
    """POST one RePORTER search for a batch of ``appl_ids``; return ``appl_id -> organization``."""
    payload = json.dumps({
        "criteria": {"appl_ids": appl_ids},
        "include_fields": ["ApplId", "Organization"],
        "limit": len(appl_ids),
        "offset": 0,
    }).encode()
    req = urllib.request.Request(
        REPORTER_SEARCH_URL,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "NIHData/0.1 (+crosswalk)"},
        method="POST",
    )

    last_err: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                body = json.loads(resp.read())
            return {r["appl_id"]: (r.get("organization") or {}) for r in body.get("results", [])}
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            time.sleep(_REQUEST_PAUSE_S * (attempt + 1))  # linear backoff

    raise RuntimeError(f"RePORTER API request failed after {_MAX_RETRIES} attempts: {last_err}")


def _org_rows_from_responses(pairs: pl.DataFrame, appl_to_org: dict[int, dict]) -> pl.DataFrame:
    """Join the per-``appl_id`` org payloads back onto the ``(duns, appl_id)`` pairs."""
    def _str(v) -> str | None:
        return None if v is None else str(v)

    records = []
    for row in pairs.iter_rows(named=True):
        org = appl_to_org.get(row["appl_id"], {})
        records.append({
            "duns": row["duns"],
            "uei": _str(org.get("primary_uei")),
            "org_name": _str(org.get("org_name")),
            "org_ipf_code": _str(org.get("org_ipf_code")),
            "api_primary_duns": _str(org.get("primary_duns")),
            "n_ueis": len(org.get("org_ueis") or []),
        })
    return pl.DataFrame(records, schema=_MAP_SCHEMA)


def build_duns_uei_map(
    df: pl.DataFrame,
    *,
    out_path: Path = DUNS_UEI_MAP_PATH,
    pause_s: float = _REQUEST_PAUSE_S,
) -> pl.DataFrame:
    """Build (and persist) the DUNS -> UEI map for the orgs present in ``df``.

    ``df`` is the wide base ExPORTER frame (it must carry ORG_DUNS, APPLICATION_ID, FY).
    """
    pairs = _representative_appl_ids(df)
    appl_ids = pairs["appl_id"].to_list()

    appl_to_org: dict[int, dict] = {}
    for i in range(0, len(appl_ids), _BATCH_SIZE):
        batch = appl_ids[i:i + _BATCH_SIZE]
        print(f"RePORTER org lookup: {i + len(batch)}/{len(appl_ids)} appl_ids")
        appl_to_org.update(_fetch_org_by_appl_ids(batch))
        if pause_s and i + _BATCH_SIZE < len(appl_ids):
            time.sleep(pause_s)

    mapping = _org_rows_from_responses(pairs, appl_to_org)

    resolved = mapping.filter(pl.col("uei").is_not_null()).height
    print(f"Resolved UEI for {resolved}/{mapping.height} DUNS.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    mapping.write_parquet(out_path)
    print(f"Wrote DUNS->UEI map to {out_path}")

    return mapping


def get_duns_uei_map(df: pl.DataFrame | None = None, *, force: bool = False) -> pl.DataFrame:
    """Return the DUNS -> UEI map, building it if missing (condition a) or ``force``-d.

    When a build is needed and no ``df`` is supplied, the all-years base frame is used.
    """
    if DUNS_UEI_MAP_PATH.exists() and not force:
        return pl.read_parquet(DUNS_UEI_MAP_PATH)

    if df is None:
        from NIHData.processing import build_dataframe_from_csv_data
        df = build_dataframe_from_csv_data()

    return build_duns_uei_map(df)
