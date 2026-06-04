"""
This object-graph parser builds an interned graph of Python objects (``Project``,
``BudgetPeriod``, ``Person`` ...) one row at a time.  This module reproduces the
*shape* of that graph as a set of normalized polars ``DataFrame``s derived from
the single wide base frame produced by ``processing.build_dataframe_from_csv_data``

In the NIH ExPORTER data, one CSV row is equivalent to one budget period. This means
that the individual objects must be extracted from each row or standardized/queryable
on their unique identifier.

Each object class maps to one frame:

    parser/objects.py            objects.py frame        grain/identifier
    -----------------            ---------------         -----
    ProjectNumber + ProjectInfo  projects               unique CORE_PROJECT_NUM
        + ProjectNarrative
    BudgetPeriod (+SerialId,     budget_periods         one per source row
        +BudgetTotals)
    Person                       people                 unique nih_person_id
    ProjectRole                  project_roles          person x application edge
    ProgramOfficer               program_officers       unique (name, institute)
    StudySection                 study_sections         unique STUDY_SECTION_NAME
    NihInstitute                 institutes             unique IC_NAME
    Organization                 organizations          unique ORG_NAME
    Address                      addresses              unique address tuple
    Department                   departments            unique (dept, org)
    ProjectNarrative             project_narratives     unique (core_num, value)
    SubprojectInfo               subprojects            unique (core, sub, year)
    ProjectTerm                  project_terms          unique term -> applications (M2M / graph)

The per-field transforms in ``parser/fields.py`` are expressed here as polars
expressions:

    DEFAULT_OPERATIONS (str.strip + blank->None) -> ``_clean``
    dt.date.fromisoformat                        -> ``_date``
    convert_to_bool                              -> ``_bool``
    handle_decimal (blank -> 0)                  -> ``_amount``
    split_on_semicolon / split_on_comma          -> ``str.split`` + ``explode``

Note: the base schema (``schemas.BASE_NIH_SCHEMA``) already typed FY/SUPPORT_YEAR
as ints and the cost columns as ``Int32`` at read time, so those need no
re-parsing here.
"""

from dataclasses import dataclass

import polars as pl

# fields.py truth sets for convert_to_bool
_TRUE_SET = ("true", "yes", "y")
_FALSE_SET = ("false", "no", "n")


# --------------------------------------------------------------------------- #
# Field-level transform helpers (mirror parser/fields.py)
# --------------------------------------------------------------------------- #
def _clean(name: str) -> pl.Expr:
    """DEFAULT_OPERATIONS: ``str.strip`` then blank string -> null."""
    e = pl.col(name).cast(pl.String).str.strip_chars()
    return pl.when(e.str.len_chars() == 0).then(None).otherwise(e)


def _date(name: str) -> pl.Expr:
    """``dt.date.fromisoformat`` -> non-strict ISO date parse (bad/blank -> null)."""
    return _clean(name).str.to_date(strict=False)


def _bool(name: str) -> pl.Expr:
    """``convert_to_bool``: members of the true/false sets, else null (vs. raising)."""
    e = _clean(name).str.to_lowercase()
    return (
        pl.when(e.is_in(_TRUE_SET)).then(True)
        .when(e.is_in(_FALSE_SET)).then(False)
        .otherwise(None)
    )


def _amount(name: str) -> pl.Expr:
    """``handle_decimal``: blank/null cost -> 0 (column is already Int32 in schema)."""
    return pl.col(name).fill_null(0)


def _strip_contact(e: pl.Expr) -> pl.Expr:
    """``Person._clean_person_component``: drop the ``(contact)`` marker + trim."""
    return e.str.replace_all("(contact)", "", literal=True).str.strip_chars()


# --------------------------------------------------------------------------- #
# Entity frames
# --------------------------------------------------------------------------- #
def institutes_frame(df: pl.DataFrame) -> pl.DataFrame:
    """NihInstitute: one row per IC_NAME, abbreviation from ADMINISTERING_IC."""
    return (
        df.select(name=_clean("IC_NAME"), abbreviation=_clean("ADMINISTERING_IC"))
        .drop_nulls("name")
        .unique(subset="name", keep="first", maintain_order=True)
    )


def organizations_frame(df: pl.DataFrame) -> pl.DataFrame:
    """Organization: one row per ORG_NAME (attributes from first occurrence)."""
    return (
        df.select(
            name=_clean("ORG_NAME"),
            ipf_code=_clean("ORG_IPF_CODE"),
            duns=_clean("ORG_DUNS"),
            fips=_clean("ORG_FIPS"),
            org_type=_clean("ED_INST_TYPE"),
        )
        .drop_nulls("name")
        .unique(subset="name", keep="first", maintain_order=True)
    )


def addresses_frame(df: pl.DataFrame) -> pl.DataFrame:
    """Address: unique by the Address hash tuple (country excluded from identity)."""
    return (
        df.select(
            organization_name=_clean("ORG_NAME"),
            city=_clean("ORG_CITY"),
            state=_clean("ORG_STATE"),
            zip_code=_clean("ORG_ZIPCODE"),
            country=_clean("ORG_COUNTRY"),
            congressional_district=_clean("ORG_DISTRICT"),
        )
        .unique(
            subset=["organization_name", "city", "state", "zip_code", "congressional_district"],
            keep="first",
            maintain_order=True,
        )
    )


def departments_frame(df: pl.DataFrame) -> pl.DataFrame:
    """Department: unique by (ORG_DEPT, ORG_NAME)."""
    return (
        df.select(name=_clean("ORG_DEPT"), organization_name=_clean("ORG_NAME"))
        .unique(subset=["name", "organization_name"], keep="first", maintain_order=True)
    )


def study_sections_frame(df: pl.DataFrame) -> pl.DataFrame:
    """StudySection: one row per STUDY_SECTION_NAME with its CORE_PROJECT_NUM list."""
    return (
        df.select(
            name=_clean("STUDY_SECTION_NAME"),
            abbreviation=_clean("STUDY_SECTION"),
            core_project_num=_clean("CORE_PROJECT_NUM"),
        )
        .drop_nulls("name")
        .group_by("name", maintain_order=True)
        .agg(
            abbreviation=pl.col("abbreviation").first(),
            projects=pl.col("core_project_num"),
        )
    )


def program_officers_frame(df: pl.DataFrame) -> pl.DataFrame:
    """ProgramOfficer: PROGRAM_OFFICER_NAME = "LAST, FIRST" -> title-cased name + institute."""
    parts = _clean("PROGRAM_OFFICER_NAME").str.split(",")
    return (
        df.select(
            last_name=parts.list.get(0, null_on_oob=True).str.strip_chars().str.to_titlecase(),
            first_name=parts.list.get(1, null_on_oob=True).str.strip_chars().str.to_titlecase(),
            institute=_clean("IC_NAME"),
        )
        .drop_nulls("last_name")
        .unique(subset=["first_name", "last_name", "institute"], keep="first", maintain_order=True)
    )


def project_terms_frame(df: pl.DataFrame) -> pl.DataFrame:
    """ProjectTerm: PROJECT_TERMS split on ';' -> term -> list of APPLICATION_IDs."""
    return (
        df.select(
            application_id=_clean("APPLICATION_ID"),
            term=_clean("PROJECT_TERMS").str.split(";"),
        )
        .explode("term")
        .with_columns(term=pl.col("term").str.strip_chars())
        .drop_nulls("term")
        .filter(pl.col("term").str.len_chars() > 0)
        .group_by("term", maintain_order=True)
        .agg(projects=pl.col("application_id"))
    )


def _exploded_people(df: pl.DataFrame) -> pl.DataFrame:
    """Shared intermediate for people/roles.

    PI_IDS / PI_NAMEs are ';'-delimited parallel lists; names are "LAST, FIRST".
    Reproduces ``Person.build_people_from_row`` element-wise.
    """
    pid_raw = pl.col("pid")
    name_parts = pl.col("pname").str.split(",")
    return (
        df.select(
            application_id=_clean("APPLICATION_ID"),
            pid=_clean("PI_IDS").str.split(";"),
            pname=_clean("PI_NAMEs").str.split(";"),
        )
        .explode("pid", "pname")  # parallel explode keeps id/name aligned
        .with_columns(
            nih_person_id=_strip_contact(pid_raw),
            is_contact=pid_raw.str.contains("(contact)", literal=True).fill_null(False),
            last_name=_strip_contact(name_parts.list.get(0, null_on_oob=True)),
            first_name=_strip_contact(name_parts.list.get(1, null_on_oob=True)),
        )
        .filter(pl.col("nih_person_id").is_not_null() & (pl.col("nih_person_id").str.len_chars() > 0))
    )


def people_frame(df: pl.DataFrame) -> pl.DataFrame:
    """Person: unique nih_person_id (first/last name from first occurrence)."""
    return (
        _exploded_people(df)
        .select("nih_person_id", "first_name", "last_name")
        .unique(subset="nih_person_id", keep="first", maintain_order=True)
    )


def project_roles_frame(df: pl.DataFrame) -> pl.DataFrame:
    """ProjectRole: unique (person, application, is_contact) edges."""
    return (
        _exploded_people(df)
        .select(
            person=pl.col("nih_person_id"),
            project=pl.col("application_id"),
            is_contact=pl.col("is_contact"),
        )
        .unique(subset=["person", "project", "is_contact"], keep="first", maintain_order=True)
    )


def project_narratives_frame(df: pl.DataFrame) -> pl.DataFrame:
    """ProjectNarrative: distinct (CORE_PROJECT_NUM, PHR), earliest SUPPORT_YEAR kept."""
    return (
        df.select(
            project_number=_clean("CORE_PROJECT_NUM"),
            value=_clean("PHR"),
            support_year=pl.col("SUPPORT_YEAR"),
        )
        .drop_nulls(["project_number", "value"])
        .group_by(["project_number", "value"], maintain_order=True)
        .agg(support_year=pl.col("support_year").min())
    )


def subprojects_frame(df: pl.DataFrame) -> pl.DataFrame:
    """SubprojectInfo: rows with a SUBPROJECT_ID, unique by (core, sub, year)."""
    return (
        df.select(
            subproject_id=_clean("SUBPROJECT_ID"),
            core_project_id=_clean("CORE_PROJECT_NUM"),
            support_year=pl.col("SUPPORT_YEAR"),
            direct_cost_amount=_amount("DIRECT_COST_AMT"),
            indirect_cost_amount=_amount("INDIRECT_COST_AMT"),
            total_cost_amount=_amount("TOTAL_COST"),
            total_cost_subproject=_amount("TOTAL_COST_SUB_PROJECT"),
        )
        .drop_nulls("subproject_id")
        .unique(
            subset=["core_project_id", "subproject_id", "support_year"],
            keep="first",
            maintain_order=True,
        )
    )


def budget_periods_frame(df: pl.DataFrame) -> pl.DataFrame:
    """BudgetPeriod: one row per source row (BudgetPeriod + SerialId + Totals + FKs)."""
    return df.select(
        # BudgetPeriod scalars
        application_id=_clean("APPLICATION_ID"),
        support_year=pl.col("SUPPORT_YEAR"),
        fiscal_year=pl.col("FY"),
        award_date=_date("AWARD_NOTICE_DATE"),
        start_date=_date("BUDGET_START"),
        end_date=_date("BUDGET_END"),
        funding_mechanism=_clean("FUNDING_MECHANISM"),
        spending_categories=_clean("NIH_SPENDING_CATS"),
        opportunity_number=_clean("OPPORTUNITY NUMBER"),
        assistance_listing_number=_clean("ASSISTANCE_LISTING_NUMBER"),
        # BudgetPeriodSerialId
        application_type=_clean("APPLICATION_TYPE"),
        full_project_number=_clean("FULL_PROJECT_NUM"),
        core_project_number=_clean("CORE_PROJECT_NUM"),
        suffix=_clean("SUFFIX"),
        # BudgetTotals
        direct_cost_amount=_amount("DIRECT_COST_AMT"),
        indirect_cost_amount=_amount("INDIRECT_COST_AMT"),
        total_cost_amount=_amount("TOTAL_COST"),
        total_cost_subproject=_amount("TOTAL_COST_SUB_PROJECT"),
        # foreign keys into the other frames
        org_name=_clean("ORG_NAME"),
        org_dept=_clean("ORG_DEPT"),
        ic_name=_clean("IC_NAME"),
        study_section_name=_clean("STUDY_SECTION_NAME"),
    )


def projects_frame(df: pl.DataFrame) -> pl.DataFrame:
    """Project: one row per CORE_PROJECT_NUM (ProjectNumber + ProjectInfo).

    Scalar ProjectInfo fields come from the first row seen for the project,
    mirroring the ``__new__`` registry; ``applications`` collects every
    APPLICATION_ID like ``ProjectNumber.applications``.
    """
    return (
        df.select(
            core_project_num=_clean("CORE_PROJECT_NUM"),
            application_id=_clean("APPLICATION_ID"),
            # ProjectNumber
            serial_number=_clean("SERIAL_NUMBER"),
            activity=_clean("ACTIVITY"),
            # ProjectInfo
            opportunity_number=_clean("OPPORTUNITY NUMBER"),
            assistance_listing_number=_clean("ASSISTANCE_LISTING_NUMBER"),
            start_date=_date("PROJECT_START"),
            end_date=_date("PROJECT_END"),
            title=_clean("PROJECT_TITLE"),
            arra_funded=_bool("ARRA_FUNDED"),
        )
        .drop_nulls("core_project_num")
        .group_by("core_project_num", maintain_order=True)
        .agg(
            serial_number=pl.col("serial_number").first(),
            activity=pl.col("activity").first(),
            opportunity_number=pl.col("opportunity_number").first(),
            assistance_listing_number=pl.col("assistance_listing_number").first(),
            start_date=pl.col("start_date").first(),
            end_date=pl.col("end_date").first(),
            title=pl.col("title").first(),
            arra_funded=pl.col("arra_funded").first(),
            applications=pl.col("application_id"),
        )
    )


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class NIHObjectFrames:
    """The full normalized object graph as polars frames."""

    projects: pl.DataFrame
    budget_periods: pl.DataFrame
    people: pl.DataFrame
    project_roles: pl.DataFrame
    program_officers: pl.DataFrame
    study_sections: pl.DataFrame
    institutes: pl.DataFrame
    organizations: pl.DataFrame
    addresses: pl.DataFrame
    departments: pl.DataFrame
    project_narratives: pl.DataFrame
    subprojects: pl.DataFrame
    project_terms: pl.DataFrame


def build_object_frames(df: pl.DataFrame) -> NIHObjectFrames:
    """Build every entity frame from the wide base dataframe.

    Public counterpart to ``parser/objects.build_project_instance`` — instead of
    interning a graph one row at a time, it derives the whole graph as frames.
    """
    return NIHObjectFrames(
        projects=projects_frame(df),
        budget_periods=budget_periods_frame(df),
        people=people_frame(df),
        project_roles=project_roles_frame(df),
        program_officers=program_officers_frame(df),
        study_sections=study_sections_frame(df),
        institutes=institutes_frame(df),
        organizations=organizations_frame(df),
        addresses=addresses_frame(df),
        departments=departments_frame(df),
        project_narratives=project_narratives_frame(df),
        subprojects=subprojects_frame(df),
        project_terms=project_terms_frame(df),
    )


def build_all_frames() -> NIHObjectFrames:
    """Build the object frames for ALL cached years and refresh the DUNS->UEI map.

    The "all" frame is the canonical full graph, so regenerating it also refreshes the
    DUNS->UEI crosswalk (it may surface organizations not seen before). See
    ``NIHData.crosswalk``.
    """
    from NIHData.processing import build_dataframe_from_csv_data
    from NIHData.crosswalk import build_duns_uei_map

    df = build_dataframe_from_csv_data()
    frames = build_object_frames(df)
    build_duns_uei_map(df)  # condition (b): a new 'all' frame refreshes the crosswalk
    return frames


def _main():
    frames = build_all_frames()
    for name in NIHObjectFrames.__dataclass_fields__:
        frame: pl.DataFrame = getattr(frames, name)
        print(f"{name:<20} {frame.shape}")


if __name__ == "__main__":
    _main()
