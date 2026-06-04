"""Guard against drift between the three places the 46-column NIH header set is defined.

``NIHData._types.NIHExporterHeader`` is the canonical column list. ``schemas.BASE_NIH_SCHEMA``
and ``columns.NIHDataColumn`` mirror it by hand, so these tests fail loudly if any of them
drifts out of sync.
"""
import polars as pl

from NIHData.domain.types import NIH_HEADER_SET, NIHExporterRowHeader
from NIHData.schemas import BASE_NIH_SCHEMA
from NIHData.columns import NIHDataColumn


def _attr_name(header: str) -> str:
    """Mirror the codegen normalization (e.g. ``OPPORTUNITY NUMBER`` -> ``OPPORTUNITY_NUMBER``)."""
    return header.strip().replace(" ", "_")


def test_schema_matches_canonical_headers():
    assert set(BASE_NIH_SCHEMA.keys()) == NIH_HEADER_SET


def test_columns_class_matches_canonical_headers():
    for header in NIHExporterRowHeader:
        attr = _attr_name(header)
        assert hasattr(NIHDataColumn, attr), (
            f"NIHDataColumn is missing attribute {attr!r} for header {header!r}"
        )
        expr = getattr(NIHDataColumn, attr)
        assert expr.meta.root_names() == [header], (
            f"NIHDataColumn.{attr} targets {expr.meta.root_names()}, expected [{header!r}]"
        )


def test_columns_class_has_no_extra_or_missing_columns():
    expected = {_attr_name(h) for h in NIH_HEADER_SET}
    defined = {
        name for name, value in vars(NIHDataColumn).items()
        if isinstance(value, pl.Expr)
    }
    assert defined == expected
