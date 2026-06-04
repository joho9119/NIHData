"""Unit tests for the network-free parts of the DUNS -> UEI crosswalk."""
import polars as pl

from NIHData.crosswalk import _org_rows_from_responses, _representative_appl_ids


def test_representative_appl_id_is_latest_fy_per_duns():
    df = pl.DataFrame({
        "ORG_DUNS": ["A", "A", "B", None],
        "APPLICATION_ID": ["1", "2", "3", "4"],
        "FY": [2019, 2024, 2020, 2024],
    })
    pairs = _representative_appl_ids(df).sort("duns")
    # null DUNS dropped; A resolves to its latest-FY appl_id (2024 -> "2")
    assert pairs["duns"].to_list() == ["A", "B"]
    assert pairs["appl_id"].to_list() == [2, 3]


def test_org_rows_join_and_unresolved_handling():
    pairs = pl.DataFrame({"duns": ["A", "B"], "appl_id": [2, 3]})
    appl_to_org = {
        2: {"primary_uei": "UEI_A", "org_name": "Org A", "org_ipf_code": "111",
            "primary_duns": "A", "org_ueis": ["UEI_A", "UEI_A2"]},
        # appl_id 3 absent -> org B unresolved
    }
    rows = _org_rows_from_responses(pairs, appl_to_org).sort("duns")

    a, b = rows.row(0, named=True), rows.row(1, named=True)
    assert a["uei"] == "UEI_A" and a["org_ipf_code"] == "111" and a["n_ueis"] == 2
    assert b["uei"] is None and b["n_ueis"] == 0
    # ipf code coerced to string even though the payload may carry an int
    assert rows.schema["org_ipf_code"] == pl.String
