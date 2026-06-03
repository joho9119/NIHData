import datetime as dt
from decimal import Decimal

from NIHData.errors import UnknownBooleanConversion

_TRUE_SET = {'true', 'yes', 'y'}
_FALSE_SET = {'false', 'no', 'n'}


def convert_to_bool(boolean_string: str) -> bool:
    boolean_string = boolean_string.lower()
    if boolean_string in _TRUE_SET:
        return True
    elif boolean_string in _FALSE_SET or boolean_string is None:
        return False
    else:
        raise UnknownBooleanConversion(f"Boolean value {boolean_string} does not match "
                                       f"any of true set ({_TRUE_SET}) or false set ({_FALSE_SET}).")


def handle_decimal(decimal_string: str | None) -> Decimal:
    if not decimal_string:
        return Decimal("0")
    else:
        return Decimal(decimal_string)


def split_on_semicolon(semicolon_separated: str) -> list[str]:
    if not semicolon_separated:
        return []
    return semicolon_separated.split(';')


def split_on_comma(comma_separated: str) -> list[str]:
    if not comma_separated:
        return []
    return comma_separated.split(',')


def split_on_comma_for_each(str_list: list[str]) -> list[tuple[str, ...]]:
    x: int = 0
    result: list[tuple[str, ...]] = []
    while x < len(str_list):
        split = split_on_comma(str_list[x])
        result.append(tuple(p.strip() for p in split))
        x += 1
    return result


def replace_blank_with_none(maybe_blank: str):
    if maybe_blank == "":
        return None
    return maybe_blank


def replace_blank_strings_with_none(container: list[tuple[str, ...]]):
    result: list[tuple[str, ...] | tuple[None]] = []

    for t in container:
        result.append(tuple((None if s == "" else s) for s in t))

    return result


def parse_data(key: str, value, row_id):
    """Public interface to transform individual fields."""
    operations = FIELD_OPERATIONS.get(key, None)

    try:
        for op in DEFAULT_OPERATIONS:
            value = op(value)

        if operations is None:
            # This is done for safety to ensure there are no changes in the raw data.
            raise KeyError(f"{key} is not present in the transformation mapping.")

        for op in operations:
            value = op(value)
            
    except ValueError as e:
        raise ValueError(f"[ROW ID: {row_id}] {key}: {value} failed conversion on operation '{op.__name__}'. Full error: {e} ")

    return value


DEFAULT_OPERATIONS = (str.strip, replace_blank_with_none)

FIELD_OPERATIONS = {
    'APPLICATION_ID': (),
    'ACTIVITY': (),
    'ADMINISTERING_IC': (),
    'APPLICATION_TYPE': (),
    'ARRA_FUNDED': (convert_to_bool,),
    'AWARD_NOTICE_DATE': (dt.date.fromisoformat,),
    'BUDGET_START': (dt.date.fromisoformat,),
    'BUDGET_END': (dt.date.fromisoformat,),
    'ASSISTANCE_LISTING_NUMBER': (),
    'CORE_PROJECT_NUM': (),
    'ED_INST_TYPE': (),
    'OPPORTUNITY NUMBER': (),
    'FULL_PROJECT_NUM': (),
    'FUNDING_ICs': (),
    'FUNDING_MECHANISM': (),
    'FY': (),
    'IC_NAME': (),
    'NIH_SPENDING_CATS': (),
    'ORG_CITY': (),
    'ORG_COUNTRY': (),
    'ORG_DEPT': (),
    'ORG_DISTRICT': (),
    'ORG_DUNS': (),
    'ORG_FIPS': (),
    'ORG_IPF_CODE': (),
    'ORG_NAME': (),
    'ORG_STATE': (),
    'ORG_ZIPCODE': (),
    'PHR': (),
    'PI_IDS': (split_on_semicolon, split_on_comma_for_each, replace_blank_strings_with_none),
    'PI_NAMEs': (split_on_semicolon, split_on_comma_for_each, replace_blank_strings_with_none),
    'PROGRAM_OFFICER_NAME': (split_on_comma,),
    'PROJECT_START': (dt.date.fromisoformat,),
    'PROJECT_END': (dt.date.fromisoformat,),
    'PROJECT_TERMS': (split_on_semicolon,),
    'PROJECT_TITLE': (),
    'SERIAL_NUMBER': (),
    'STUDY_SECTION': (),
    'STUDY_SECTION_NAME': (),
    'SUBPROJECT_ID': (replace_blank_with_none, ),
    'SUFFIX': (),
    'SUPPORT_YEAR': (),
    'DIRECT_COST_AMT': (handle_decimal,),
    'INDIRECT_COST_AMT': (handle_decimal,),
    'TOTAL_COST': (handle_decimal,),
    'TOTAL_COST_SUB_PROJECT': (handle_decimal,)
}
