"""Set-returning discovery table functions for the conform worker.

These expand to **many rows**, so they are exposed as **table functions** -- the
form that accepts DuckDB ``name := value`` arguments (none of these take any
arguments, but the table-function shape is still the right home for them). The
per-row, single-value conform functions are *scalars* and live in
:mod:`vgi_conform.scalars`.

    SELECT * FROM conform.supported_phone_regions() ORDER BY region;
    SELECT * FROM conform.card_brands() ORDER BY brand;
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import pyarrow as pa
from vgi.metadata import FunctionExample
from vgi.table_function import (
    BindParams,
    ProcessParams,
    TableCardinality,
    TableFunctionGenerator,
    bind_fixed_schema,
    init_single_worker,
)
from vgi_rpc.rpc import OutputCollector

from . import validators
from .meta import function_tags
from .schema_utils import field

_TABLES_PATH = "vgi_conform/tables.py"


@dataclass(kw_only=True)
class _NoArgs:
    """A discovery table function that takes no arguments."""


_PHONE_REGIONS_SCHEMA = pa.schema(
    [
        field("region", pa.string(), "ISO-3166 alpha-2 region code.", nullable=False),
        field("country_code", pa.int32(), "International dialling (country calling) code.", nullable=False),
    ]
)


@init_single_worker
@bind_fixed_schema
class SupportedPhoneRegionsFunction(TableFunctionGenerator[_NoArgs]):
    """Every ``(region, country_code)`` the phone functions understand.

    ``region`` is the value you pass as the optional ``region`` argument to the
    phone scalars (``is_valid_phone(text, region)`` etc.); ``country_code`` is
    its international dialling prefix.
    """

    FIXED_SCHEMA: ClassVar[pa.Schema] = _PHONE_REGIONS_SCHEMA

    class Meta:
        """Function metadata."""

        name = "supported_phone_regions"
        description = "Every (region, country_code) the phone functions support"
        categories = ["conform", "phone"]
        tags = function_tags(
            title="List Supported Phone Regions",
            description_llm=(
                "## `supported_phone_regions()`\n\n"
                "A **table function** (no arguments) returning one row per phone region the "
                "phone scalars understand, with columns:\n\n"
                "- `region` (`VARCHAR`) -- the ISO-3166 alpha-2 code you pass as the "
                "optional `region` argument to `is_valid_phone(text, region)`, the phone "
                "formatters, `phone_region`, and `phone_type`.\n"
                "- `country_code` (`INTEGER`) -- its international dialling (country "
                "calling) code.\n\n"
                "Use it to discover valid region values or to look up a country's dialling "
                "code (`SELECT country_code FROM conform.supported_phone_regions() WHERE "
                "region = 'GB'`)."
            ),
            description_md=(
                "# `supported_phone_regions`\n\n"
                "Discovery table of every phone region the worker understands.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT * FROM conform.supported_phone_regions() ORDER BY region;\n"
                "```\n\n"
                "## Columns\n\n"
                "- `region` (VARCHAR) -- ISO-3166 alpha-2 region code.\n"
                "- `country_code` (INTEGER) -- international dialling code."
            ),
            keywords="phone, regions, supported regions, country code, dialling code, discovery",
            relative_path=_TABLES_PATH,
            extra={
                "vgi.result_columns_md": (
                    "| column | type | description |\n"
                    "| --- | --- | --- |\n"
                    "| `region` | VARCHAR | ISO-3166 alpha-2 region code (the optional `region` argument). |\n"
                    "| `country_code` | INTEGER | International dialling (country calling) code. |\n"
                ),
            },
        )
        examples = [
            FunctionExample(
                sql="SELECT count(*) FROM conform.supported_phone_regions()",
                description="How many phone regions are supported",
            ),
            FunctionExample(
                sql="SELECT country_code FROM conform.supported_phone_regions() WHERE region = 'GB'",
                description="Dialling code for the UK",
            ),
        ]

    @classmethod
    def cardinality(cls, params: BindParams[_NoArgs]) -> TableCardinality:
        """Estimated and maximum row count for the planner."""
        return TableCardinality(estimate=250, max=1000)

    @classmethod
    def process(cls, params: ProcessParams[_NoArgs], state: None, out: OutputCollector) -> None:
        """Emit one batch of discovery rows."""
        rows = validators.supported_phone_regions()
        out.emit(
            pa.RecordBatch.from_pydict(
                {
                    "region": [r[0] for r in rows],
                    "country_code": [r[1] for r in rows],
                },
                schema=params.output_schema,
            )
        )
        out.finish()


_CARD_BRANDS_SCHEMA = pa.schema([field("brand", pa.string(), "A brand card_brand() can return.", nullable=False)])


@init_single_worker
@bind_fixed_schema
class CardBrandsFunction(TableFunctionGenerator[_NoArgs]):
    """The brands the ``card_brand`` scalar can return, one per row."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = _CARD_BRANDS_SCHEMA

    class Meta:
        """Function metadata."""

        name = "card_brands"
        description = "The brands card_brand() can return (visa, mastercard, amex, ...)"
        categories = ["conform", "card"]
        tags = function_tags(
            title="List Recognized Card Brands",
            description_llm=(
                "## `card_brands()`\n\n"
                "A **table function** (no arguments) returning one row per card brand the "
                "`card_brand` scalar can emit, with a single column:\n\n"
                "- `brand` (`VARCHAR`) -- a brand name such as `visa`, `mastercard`, "
                "`amex`, `discover`, `diners`, `jcb`.\n\n"
                "Use it to enumerate the recognized brands -- e.g. to populate a UI filter "
                "or to validate that a `card_brand(...)` result is within the known set."
            ),
            description_md=(
                "# `card_brands`\n\n"
                "Discovery table of every brand `card_brand()` can return.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT * FROM conform.card_brands() ORDER BY brand;\n"
                "```\n\n"
                "## Columns\n\n"
                "- `brand` (VARCHAR) -- e.g. `visa`, `mastercard`, `amex`."
            ),
            keywords="credit card, card brands, visa, mastercard, amex, discover, jcb, discovery",
            relative_path=_TABLES_PATH,
            extra={
                "vgi.result_columns_md": (
                    "| column | type | description |\n"
                    "| --- | --- | --- |\n"
                    "| `brand` | VARCHAR | A brand `card_brand()` can return, e.g. `visa`, `mastercard`, `amex`. |\n"
                ),
            },
        )
        examples = [
            FunctionExample(
                sql="SELECT * FROM conform.card_brands() ORDER BY brand",
                description="List the recognized card brands",
            ),
        ]

    @classmethod
    def cardinality(cls, params: BindParams[_NoArgs]) -> TableCardinality:
        """Estimated and maximum row count for the planner."""
        return TableCardinality(estimate=6, max=6)

    @classmethod
    def process(cls, params: ProcessParams[_NoArgs], state: None, out: OutputCollector) -> None:
        """Emit one batch of discovery rows."""
        out.emit(
            pa.RecordBatch.from_pydict(
                {"brand": validators.card_brands()},
                schema=params.output_schema,
            )
        )
        out.finish()


TABLE_FUNCTIONS: list[type] = [
    SupportedPhoneRegionsFunction,
    CardBrandsFunction,
]
