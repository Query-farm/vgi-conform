"""Composed example queries are wired into every place they are advertised.

Each composed SQL (``vgi_conform.examples``) must appear in the schema-level
``vgi.example_queries``, among the first five examples of the object that drives
it (the agent simulator only shows those), and in ``vgi.executable_examples``.
Their output is pinned end-to-end by ``test/sql/composed.test``.
"""

from __future__ import annotations

import json

import pytest
from vgi.metadata import FunctionExample

from vgi_conform import examples
from vgi_conform.scalars import (
    IbanCountryFunction,
    MaskCardFunction,
    NormalizeEmailFunction,
    PhoneRegionFunction,
)
from vgi_conform.worker import _CONFORM_CATALOG

_SCHEMA = _CONFORM_CATALOG.schemas[0]


def _sqls(tag_value: str) -> list[str]:
    return [entry["sql"] for entry in json.loads(tag_value)]


@pytest.mark.parametrize("example", examples.COMPOSED_EXAMPLES, ids=lambda ex: ex.description[:40])
def test_in_schema_and_executable_lists(example: FunctionExample) -> None:
    assert example.sql in _sqls(_SCHEMA.tags["vgi.example_queries"])
    assert example.sql in _sqls(MaskCardFunction.Meta.tags["vgi.executable_examples"])


@pytest.mark.parametrize(
    ("example", "fn"),
    [
        (examples.EMAIL_DOMAIN_DEDUP, NormalizeEmailFunction),
        (examples.PHONE_COUNTRY_MISMATCH, PhoneRegionFunction),
        (examples.SUPPLIER_IBAN_VAT, IbanCountryFunction),
    ],
)
def test_on_driving_function(example: FunctionExample, fn: type) -> None:
    assert example.sql in _sqls(fn.Meta.tags["vgi.example_queries"])[:5]  # type: ignore[attr-defined]


def test_card_coverage_on_card_brands_table() -> None:
    table = next(t for t in _SCHEMA.tables if t.name == "card_brands")
    assert examples.CARD_BRAND_COVERAGE_SQL in _sqls(table.tags["vgi.example_queries"])[:5]
