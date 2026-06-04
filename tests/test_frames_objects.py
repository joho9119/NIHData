"""Validate that ``frames.objects`` derives each entity frame at the right grain.

The object-graph parser (``parser/objects.py``) deduplicates/interns one row at a time; the
polars ``frames.objects`` module reproduces that shape as normalized frames. These tests use a
tiny synthetic base DataFrame (two budget periods of one core project + a second project) and
assert the grain, dedup, field transforms, and ``(contact)`` cleaning all match.
"""
import datetime as dt

import polars as pl
import pytest

from NIHData.schemas import BASE_NIH_SCHEMA
from NIHData.frames.objects import build_object_frames, NIHObjectFrames


def _row(**overrides):
    base = {name: None for name in BASE_NIH_SCHEMA.keys()}
    base.update(overrides)
    return base


@pytest.fixture(scope="module")
def frames() -> NIHObjectFrames:
    rows = [
        _row(  # FY1 budget period of project A; contact PI + co-PI
            APPLICATION_ID="100", ACTIVITY="R01", ADMINISTERING_IC="NIMH", APPLICATION_TYPE="1",
            ARRA_FUNDED="N", AWARD_NOTICE_DATE="2020-01-15", BUDGET_START="2020-02-01",
            BUDGET_END="2021-01-31", ASSISTANCE_LISTING_NUMBER="93.242",
            CORE_PROJECT_NUM="R01MH111", ED_INST_TYPE="SCHOOLS OF MEDICINE",
            **{"OPPORTUNITY NUMBER": "PA-19-056"}, FULL_PROJECT_NUM="1R01MH111-01",
            FUNDING_MECHANISM="RPG", FY=2020, IC_NAME="National Institute of Mental Health",
            ORG_CITY="BALTIMORE", ORG_COUNTRY="UNITED STATES", ORG_DEPT="PSYCHIATRY",
            ORG_DISTRICT="07", ORG_DUNS="001", ORG_FIPS="US", ORG_IPF_CODE="IPF1",
            ORG_NAME="JOHNS HOPKINS UNIVERSITY", ORG_STATE="MD", ORG_ZIPCODE="21218",
            PHR="Narrative text A", PI_IDS="7117069 (contact); 9409588",
            PI_NAMEs="CALHOUN, VINCE D (contact); LIU, JINGYU", PROGRAM_OFFICER_NAME="SMITH, JOHN A",
            PROJECT_START="2019-09-01", PROJECT_END="2024-08-31", PROJECT_TERMS="brain; imaging; ",
            PROJECT_TITLE="Project A Title", SERIAL_NUMBER="111", STUDY_SECTION="ZRG1",
            STUDY_SECTION_NAME="Special Emphasis Panel", SUBPROJECT_ID="", SUPPORT_YEAR=1,
            DIRECT_COST_AMT=500000, INDIRECT_COST_AMT=200000, TOTAL_COST=700000,
            TOTAL_COST_SUB_PROJECT=None,
        ),
        _row(  # FY2 budget period of the SAME project A; has a subproject
            APPLICATION_ID="200", ACTIVITY="R01", ADMINISTERING_IC="NIMH", APPLICATION_TYPE="5",
            ARRA_FUNDED="N", AWARD_NOTICE_DATE="2021-01-15", BUDGET_START="2021-02-01",
            BUDGET_END="2022-01-31", ASSISTANCE_LISTING_NUMBER="93.242",
            CORE_PROJECT_NUM="R01MH111", ED_INST_TYPE="SCHOOLS OF MEDICINE",
            **{"OPPORTUNITY NUMBER": "PA-19-056"}, FULL_PROJECT_NUM="5R01MH111-02",
            FUNDING_MECHANISM="RPG", FY=2021, IC_NAME="National Institute of Mental Health",
            ORG_CITY="BALTIMORE", ORG_COUNTRY="UNITED STATES", ORG_DEPT="PSYCHIATRY",
            ORG_DISTRICT="07", ORG_DUNS="001", ORG_FIPS="US", ORG_IPF_CODE="IPF1",
            ORG_NAME="JOHNS HOPKINS UNIVERSITY", ORG_STATE="MD", ORG_ZIPCODE="21218",
            PHR="Narrative text A", PI_IDS="7117069 (contact)",
            PI_NAMEs="CALHOUN, VINCE D (contact)", PROGRAM_OFFICER_NAME="SMITH, JOHN A",
            PROJECT_START="2019-09-01", PROJECT_END="2024-08-31", PROJECT_TERMS="brain; cognition",
            PROJECT_TITLE="Project A Title", SERIAL_NUMBER="111", STUDY_SECTION="ZRG1",
            STUDY_SECTION_NAME="Special Emphasis Panel", SUBPROJECT_ID="5001", SUPPORT_YEAR=2,
            DIRECT_COST_AMT=510000, INDIRECT_COST_AMT=210000, TOTAL_COST=720000,
            TOTAL_COST_SUB_PROJECT=50000,
        ),
        _row(  # project B: foreign org, no program officer, ARRA funded, blank narrative
            APPLICATION_ID="300", ACTIVITY="U01", ADMINISTERING_IC="NCI", APPLICATION_TYPE="1",
            ARRA_FUNDED="Y", AWARD_NOTICE_DATE="2022-03-10", BUDGET_START="2022-04-01",
            BUDGET_END="2023-03-31", ASSISTANCE_LISTING_NUMBER="93.395",
            CORE_PROJECT_NUM="U01CA222", ED_INST_TYPE="", **{"OPPORTUNITY NUMBER": "RFA-CA-21-001"},
            FULL_PROJECT_NUM="1U01CA222-01", FUNDING_MECHANISM="RPG", FY=2022,
            IC_NAME="National Cancer Institute", ORG_CITY="LONDON", ORG_COUNTRY="UNITED KINGDOM",
            ORG_DEPT="ONCOLOGY", ORG_DISTRICT="", ORG_DUNS="999", ORG_FIPS="UK",
            ORG_IPF_CODE="IPF9", ORG_NAME="UNIVERSITY OF LONDON", ORG_STATE="", ORG_ZIPCODE="WC1",
            PHR="", PI_IDS="1234567", PI_NAMEs="DOE, JANE", PROGRAM_OFFICER_NAME="",
            PROJECT_START="2022-04-01", PROJECT_END="2025-03-31", PROJECT_TERMS="cancer",
            PROJECT_TITLE="Project B Title", SERIAL_NUMBER="222", STUDY_SECTION="",
            STUDY_SECTION_NAME="", SUBPROJECT_ID="", SUPPORT_YEAR=1, DIRECT_COST_AMT=100000,
            INDIRECT_COST_AMT=40000, TOTAL_COST=140000, TOTAL_COST_SUB_PROJECT=None,
        ),
    ]
    df = pl.DataFrame(rows, schema=BASE_NIH_SCHEMA)
    return build_object_frames(df)


def test_budget_periods_are_one_per_source_row(frames):
    assert frames.budget_periods.height == 3


def test_projects_unique_on_core_project_num(frames):
    assert frames.projects.height == 2
    assert frames.projects["core_project_num"].n_unique() == 2
    apps = frames.projects.filter(pl.col("core_project_num") == "R01MH111")["applications"].item()
    assert apps.to_list() == ["100", "200"]


def test_people_dedup_and_contact_cleaning(frames):
    assert frames.people.height == 3
    cal = frames.people.filter(pl.col("nih_person_id") == "7117069")
    assert cal.height == 1
    assert cal["first_name"].item() == "VINCE D"
    assert cal["last_name"].item() == "CALHOUN"


def test_project_roles_flag_contact(frames):
    contact = frames.project_roles.filter(
        (pl.col("person") == "7117069") & pl.col("is_contact")
    )
    assert contact.height >= 1
    non_contact = frames.project_roles.filter(pl.col("person") == "9409588")
    assert non_contact["is_contact"].to_list() == [False]


def test_program_officer_name_split_and_titlecase(frames):
    assert frames.program_officers.height == 1
    po = frames.program_officers.row(0, named=True)
    assert po["first_name"] == "John A"
    assert po["last_name"] == "Smith"
    assert po["institute"] == "National Institute of Mental Health"


def test_lookup_frames_grain(frames):
    assert frames.institutes.height == 2
    assert frames.organizations.height == 2
    assert frames.departments.height == 2
    assert frames.addresses.height == 2


def test_subprojects_only_when_present(frames):
    assert frames.subprojects.height == 1
    assert frames.subprojects["subproject_id"].item() == "5001"


def test_narrative_drops_blank_and_dedups(frames):
    # project A repeats the same PHR across two rows -> one; project B blank -> dropped.
    assert frames.project_narratives.height == 1
    assert frames.project_narratives["project_number"].item() == "R01MH111"


def test_project_terms_explode_and_group(frames):
    terms = dict(zip(frames.project_terms["term"], frames.project_terms["projects"].to_list()))
    assert terms["brain"] == ["100", "200"]
    assert terms["imaging"] == ["100"]


def test_field_transforms(frames):
    bp = frames.budget_periods
    assert bp["start_date"].dtype == pl.Date
    assert bp.filter(pl.col("application_id") == "100")["start_date"].item() == dt.date(2020, 2, 1)
    # handle_decimal: null cost -> 0
    assert bp.filter(pl.col("application_id") == "100")["total_cost_subproject"].item() == 0
    # convert_to_bool
    assert frames.projects.filter(pl.col("core_project_num") == "U01CA222")["arra_funded"].item() is True
    assert frames.projects.filter(pl.col("core_project_num") == "R01MH111")["arra_funded"].item() is False
