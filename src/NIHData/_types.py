from builtins import tuple
from collections.abc import Callable
from typing import Literal, Any, get_args

NIHExporterHeader = Literal[
    'APPLICATION_ID', 'ACTIVITY', 'ADMINISTERING_IC', 'APPLICATION_TYPE', 'ARRA_FUNDED',
    'AWARD_NOTICE_DATE', 'BUDGET_START', 'BUDGET_END', 'ASSISTANCE_LISTING_NUMBER', 'CORE_PROJECT_NUM',
    'ED_INST_TYPE', 'OPPORTUNITY NUMBER', 'FULL_PROJECT_NUM', 'FUNDING_ICs', 'FUNDING_MECHANISM', 'FY',
    'IC_NAME', 'NIH_SPENDING_CATS', 'ORG_CITY', 'ORG_COUNTRY', 'ORG_DEPT', 'ORG_DISTRICT', 'ORG_DUNS',
    'ORG_FIPS', 'ORG_IPF_CODE', 'ORG_NAME', 'ORG_STATE', 'ORG_ZIPCODE', 'PHR', 'PI_IDS', 'PI_NAMEs',
    'PROGRAM_OFFICER_NAME', 'PROJECT_START', 'PROJECT_END', 'PROJECT_TERMS', 'PROJECT_TITLE',
    'SERIAL_NUMBER', 'STUDY_SECTION', 'STUDY_SECTION_NAME', 'SUBPROJECT_ID', 'SUFFIX', 'SUPPORT_YEAR',
    'DIRECT_COST_AMT', 'INDIRECT_COST_AMT', 'TOTAL_COST', 'TOTAL_COST_SUB_PROJECT'
]

NIHExporterRow = dict[NIHExporterHeader, Any]
NIHExporterRowHeader: tuple[NIHExporterHeader] = get_args(NIHExporterHeader)
NIH_HEADER_SET: set[NIHExporterHeader] = {*get_args(NIHExporterHeader)}

_OptionsTo = Literal['dict', 'typeddict', 'enum', 'list',  'tuple', 'set']


def _main(target_type, to: _OptionsTo):
    from typing import get_args
    base_args: tuple[str, ...] = get_args(target_type)

    translate: dict[Literal['list', 'tuple', 'set'], Callable] = {
        'list': list,
        'tuple': tuple,
        'set': set
    }

    if to == 'dict':
        return {k: None for k in base_args}
    elif to == 'typeddict':
        return "\n".join([
            "class NIHExporterBaseField(typing.TypedDict):",
            "\n".join((f"    {k}: str" for k in base_args))
        ])
    elif to == 'enum':
        return "\n".join([
            "class NIHExporterBaseField(enum.StrEnum):",
            "\n".join((f"    {k.strip().replace(' ', '_')} = \"{k}\"" for k in base_args))
        ])
    else:
        return translate[to](base_args)


if __name__ == "__main__":
    print(_main(NIHExporterHeader, 'tuple'))
