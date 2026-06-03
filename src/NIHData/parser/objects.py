import datetime as dt
from typing import Any

type ExporterRow = dict[str, Any]


class ProjectTerm:
    __slots__ = ("term", "projects")
    _registry: dict[str, ProjectTerm] = {}
    term: str
    projects: list[str]

    def __new__(cls, term: str, row: ExporterRow) -> ProjectTerm:
        if (existing := cls._registry.get(term)) is not None:
            existing.projects.append(row.get('APPLICATION_ID'))
            return existing

        instance = super().__new__(cls)
        instance.term = term
        instance.projects = []
        instance.projects.append(row.get('APPLICATION_ID'))
        cls._registry[term] = instance
        return instance

    def __hash__(self) -> int:
        return hash(self.term)

    @classmethod
    def __getitem__(cls, item: str) -> ProjectTerm:
        return cls._registry[item]

    def __str__(self) -> str:
        return self.term


class ProjectRole:
    __slots__ = ("person", "project", "is_contact")

    def __init__(self, *, person_id: str, project_id: str, is_contact: bool):
        """This will be unique by person/project/role, so no need to do a uniqueness check."""
        self.person = person_id
        self.project = project_id
        self.is_contact = is_contact

    def __hash__(self):
        return hash((self.person, self.project, self.is_contact))


class Person:
    __slots__ = ("nih_person_id", "first_name", "last_name",)
    _person_registry: dict[str, Person] = dict()
    _project_relationship_registry: dict[str, list[ProjectRole]] = dict()

    def __new__(cls, *, nih_person_id: str, first_name: str, last_name: str, row: ExporterRow):
        application_id = row['APPLICATION_ID']
        is_contact = "(contact)" in nih_person_id
        person_id = cls._clean_person_component(nih_person_id)
        project_role = ProjectRole(person_id=person_id, project_id=application_id, is_contact=is_contact)

        if (instance := cls._person_registry.get(person_id)) is not None:
            cls._project_relationship_registry.setdefault(application_id, []).append(project_role)
            return instance

        instance = super().__new__(cls)
        instance.nih_person_id = person_id
        instance.first_name = cls._clean_person_component(first_name)
        instance.last_name = cls._clean_person_component(last_name)

        cls._person_registry[person_id] = instance
        cls._project_relationship_registry.setdefault(application_id, []).append(project_role)

        return instance

    def __hash__(self):
        return hash(self.nih_person_id)

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.nih_person_id})"

    @staticmethod
    def _clean_person_component(c: str):
        return c.replace("(contact)", "").strip()

    @classmethod
    def build_people_from_row(cls, row: ExporterRow):
        iterator = zip(row.pop("PI_IDS"), row.pop("PI_NAMEs"))
        # (['7117069 (contact)'], ['CALHOUN', 'VINCE D (contact)'])
        # (['9409588'], ['LIU', 'JINGYU'])
        result = []
        for person_data in iterator:
            id_data, name_data = person_data
            if id_data[0] is None:
                continue
            result.append(cls(
                nih_person_id=id_data[0], first_name=name_data[1], last_name=name_data[0], row=row
            ))
        return result


class ProgramOfficer:
    __slots__ = ("po_id", "first_name", "last_name", "institute",)
    _registry = dict()

    def __new__(cls, row: ExporterRow, institute: NihInstitute):
        parts: list[str] = row.get("PROGRAM_OFFICER_NAME")
        if not parts or not parts[0]:
            return None

        first_name = parts[1].title()
        last_name = parts[0].title()
        po_id = hash((first_name, last_name, institute))

        if (instance := cls._registry.get(po_id)) is not None:
            return instance

        instance = super().__new__(cls)

        instance.po_id = po_id
        instance.first_name = first_name
        instance.last_name = last_name

        cls._registry[po_id] = instance
        return instance


class StudySection:
    __slots__ = ("name", "abbreviation", "projects")
    _registry: dict[str, StudySection] = dict()
    projects: list[str]
    name: str
    abbreviation: str

    def __new__(cls, row: ExporterRow):
        project_id = row['CORE_PROJECT_NUM']
        name = row.get("STUDY_SECTION_NAME")

        if (instance := cls._registry.get(name)) is not None:
            instance.projects.append(project_id)
            return instance

        instance = super().__new__(cls)

        instance.name = name
        instance.abbreviation = row.get("STUDY_SECTION")
        instance.projects = []
        instance.projects.append(project_id)
        cls._registry[name] = instance

        return instance


class NihInstitute:
    __slots__ = ("name", "abbreviation")
    _registry: dict[str, NihInstitute] = dict()

    def __new__(cls, row: ExporterRow):
        name = row.get("IC_NAME")
        if (instance := cls._registry.get(name)) is not None:
            return instance

        instance = super().__new__(cls)

        instance.name = name
        instance.abbreviation = row.get("ADMINISTERING_IC")

        cls._registry[name] = instance
        return instance

    def __hash__(self):
        return hash(self.name)


class Address:
    __slots__ = (
        "organization_name", "city", "state", "zip_code", "country", "congressional_district",
    )

    def __init__(self, organization_name: str, row: ExporterRow):
        self.organization_name = organization_name
        self.city = row.get("ORG_CITY")
        self.state = row.get("ORG_STATE")
        self.zip_code = row.get("ORG_ZIPCODE")
        self.country = row.get('ORG_COUNTRY')
        self.congressional_district = row.get('ORG_DISTRICT')

    def __eq__(self, other: Address):
        return hash(self) == hash(other)

    def __hash__(self):
        return hash((self.organization_name, self.city, self.state, self.zip_code, self.congressional_district))


class Organization:
    __slots__ = ("name", "addresses", "ipf_code", "duns", "fips", "org_type",)
    _registry: dict[str, Organization] = dict()

    name: str
    ipf_code: str
    duns: str
    fips: str
    org_type: str
    addresses: list[Address]

    def __new__(cls, row: ExporterRow):
        name: str = row.get("ORG_NAME")
        address = Address(name, row)
        if (instance := cls._registry.get(name)) is not None:
            if not any(a == address for a in instance.addresses):
                instance.addresses.append(address)
            return instance

        instance = super().__new__(cls)

        instance.name = name
        instance.ipf_code = row.get("ORG_IPF_CODE")
        instance.duns = row.get('ORG_DUNS')
        instance.fips = row.get('ORG_FIPS')
        instance.org_type = row.get("ED_INST_TYPE")
        instance.addresses = [address]

        return instance

    def __hash__(self):
        return hash((self.name, self.ipf_code))


class Department:
    __slots__ = ("name", "organization_name")
    _registry: dict[tuple[str, str], Department] = dict()

    def __new__(cls, row: ExporterRow):
        dept_name = row.get("ORG_DEPT")
        org_name = row.get("ORG_NAME")

        if (instance := cls._registry.get((dept_name, org_name))) is not None:
            return instance

        instance = super().__new__(cls)
        instance.name = dept_name
        instance.organization_name = org_name

        cls._registry[(instance.name, instance.organization_name)] = instance
        return instance

    def __hash__(self):
        return hash((self.name, self.organization_name))


class ProjectNarrative:
    __slots__ = ("value", "project_number")
    _registry: dict[str, list[tuple[int, ProjectNarrative]]] = dict()
    value: str
    project_number: str

    def __new__(cls, row: ExporterRow):
        value = row.get("PHR")
        core_project_num = row.get("CORE_PROJECT_NUM")

        if not value or not core_project_num:
            return None

        if (instances := cls._registry.get(core_project_num)) is not None:
            if all(x[1].value == value for x in instances):
                return instances[-1][1]

        instance = super().__new__(cls)
        instance.value = value
        instance.project_number = core_project_num
        support_year = row.get("SUPPORT_YEAR")
        cls._registry.setdefault(core_project_num, []).append((support_year, instance))
        return instance

    def __eq__(self, other):
        if hasattr(other, "value"):
            return self.value == other.value
        else:
            return self.value == other

    def __hash__(self):
        return hash(self.value)


class BudgetPeriodSerialId:
    __slots__ = (
        "application_id", "application_type", "full_project_number",
        "core_project_number", "support_year", "suffix",
    )

    def __init__(self, row: ExporterRow):
        self.application_type: str = row.get("APPLICATION_TYPE")
        self.full_project_number: str = row.get("FULL_PROJECT_NUM")
        self.core_project_number: str = row.get("CORE_PROJECT_NUM")
        self.support_year = row.get("SUPPORT_YEAR")
        self.suffix: str = row.get("SUFFIX")

    def __hash__(self):
        return hash(self.full_project_number)


class BudgetTotals:
    __slots__ = (
        "direct_cost_amount", "indirect_cost_amount", "total_cost_amount", "total_cost_subproject"
    )

    def __init__(self, row: ExporterRow):
        self.direct_cost_amount = row.get("DIRECT_COST_AMT")
        self.indirect_cost_amount = row.get("INDIRECT_COST_AMT")
        self.total_cost_amount = row.get("TOTAL_COST")
        self.total_cost_subproject = row.get("TOTAL_COST_SUB_PROJECT")


class BudgetPeriod:
    __slots__ = (
        "application_id", "support_year", "fiscal_year", "award_date", "start_date", "end_date",
        "funding_mechanism", "spending_categories", "opportunity_number", "assistance_listing_number",
        "budget_period_id", "amounts", "program_officer",
        "people", "project_terms", "organization", "department", "funding_institute", "study_section"
    )

    def __init__(self, row: ExporterRow):
        """
        Each row represents a budget period/additional funding. No need to deduplicate.
        """
        self.application_id = row.get("APPLICATION_ID")
        self.support_year = row.get("SUPPORT_YEAR")
        self.fiscal_year = row.get("FY")
        self.award_date = row.get("AWARD_NOTICE_DATE")
        self.start_date = row.get("BUDGET_START")
        self.end_date = row.get("BUDGET_END")
        self.funding_mechanism = row.get("FUNDING_MECHANISM")
        self.spending_categories = row.get("NIH_SPENDING_CATS")
        self.opportunity_number: str = row.get("OPPORTUNITY NUMBER")
        self.assistance_listing_number: str = row.get("ASSISTANCE_LISTING_NUMBER")

        self.budget_period_id = BudgetPeriodSerialId(row)
        self.program_officer = ProgramOfficer(row, institute=NihInstitute(row))
        self.amounts = BudgetTotals(row)
        self.people = Person.build_people_from_row(row)
        self.project_terms: list[ProjectTerm] = [ProjectTerm(part, row) for part in row.get("PROJECT_TERMS")]
        self.organization = Organization(row)
        self.department = Department(row)
        self.funding_institute = NihInstitute(row)
        self.study_section = StudySection(row)


class ProjectNumber:
    __slots__ = ("value", "serial_number", "activity", "applications")
    _registry: dict[str, ProjectNumber] = dict()

    value: str
    serial_number: str
    activity: str
    applications: list[str]

    def __new__(cls, row: ExporterRow):
        core_project_number: str = row.get("CORE_PROJECT_NUM")
        application_id: str = row.get("APPLICATION_ID")

        if (instance := cls._registry.get(core_project_number)) is not None:
            instance.applications.append(application_id)
            return instance

        instance = super().__new__(cls)
        instance.value = core_project_number
        instance.serial_number = row.get("SERIAL_NUMBER")
        instance.activity = row.get("ACTIVITY")
        instance.applications = [application_id]
        instance._registry[core_project_number] = instance

        return instance

    def __hash__(self):
        return hash(self.value)

class SubprojectInfo:
    def __new__(cls, row: ExporterRow):
        core_project_number: str = row.get("CORE_PROJECT_NUM")
        

        instance = super().__new__(cls)


        return instance


class ProjectInfo:
    __slots__ = ("opportunity_number", "assistance_listing_number", "start_date", "end_date", "title", "arra_funded")
    opportunity_number: str
    assistance_listing_number: str
    start_date: dt.date
    end_date: dt.date
    title: str
    arra_funded: bool

    def __init__(self, row: ExporterRow):
        self.opportunity_number = row.get("OPPORTUNITY NUMBER")
        self.assistance_listing_number = row.get("ASSISTANCE_LISTING_NUMBER")
        self.start_date = row.get("PROJECT_START")
        self.end_date = row.get("PROJECT_END")
        self.title = row.get("PROJECT_TITLE")
        self.arra_funded = row.get("ARRA_FUNDED")



class Project:
    __slots__ = ("info", "budget_periods", "project_number", "narrative")
    _registry: dict[ProjectNumber, Project] = dict()

    info: ProjectInfo
    project_number: ProjectNumber
    budget_periods: list[BudgetPeriod]
    narrative: ProjectNarrative

    def __new__(cls, row: ExporterRow):
        project_number = ProjectNumber(row)
        if (instance := cls._registry.get(project_number)) is not None:
            bp = BudgetPeriod(row)
            if bp not in instance.budget_periods:
                instance.budget_periods.append(bp)
            return instance

        instance = super().__new__(cls)

        instance.info = ProjectInfo(row)
        instance.project_number = project_number
        instance.budget_periods = [BudgetPeriod(row), ]
        instance.narrative = ProjectNarrative(row)
        return instance


def build_project_instance(row: ExporterRow):
    """Public method to construct instances of Project."""
    return Project(row)
