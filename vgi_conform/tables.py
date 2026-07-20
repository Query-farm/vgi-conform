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

import json
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
                "code (filter by `region` to read one country's `country_code`)."
            ),
            description_md=(
                "# `supported_phone_regions`\n\n"
                "Discovery table of every phone region the worker understands.\n\n"
                "## Columns\n\n"
                "- `region` (`VARCHAR`) -- ISO-3166 alpha-2 region code.\n"
                "- `country_code` (`INTEGER`) -- international dialling code."
            ),
            keywords="phone, regions, supported regions, country code, dialling code, discovery",
            relative_path=_TABLES_PATH,
            extra={
                # VGI414: the retired free-form `vgi.result_columns_md` is migrated to the
                # structured `vgi.result_columns_schema` (validated JSON: name/type/description).
                "vgi.result_columns_schema": json.dumps(
                    [
                        {
                            "name": "region",
                            "type": "VARCHAR",
                            "description": (
                                "ISO-3166 alpha-2 region code (the optional `region` argument to the phone functions)."
                            ),
                        },
                        {
                            "name": "country_code",
                            "type": "INTEGER",
                            "description": "International dialling (country calling) code.",
                        },
                    ]
                ),
            },
        )
        examples = [
            FunctionExample(
                sql="SELECT count(*) AS regions FROM conform.main.supported_phone_regions()",
                description="How many phone regions are supported",
            ),
            FunctionExample(
                sql="SELECT country_code FROM conform.main.supported_phone_regions() WHERE region = 'GB'",
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
                "## Columns\n\n"
                "- `brand` (`VARCHAR`) -- e.g. `visa`, `mastercard`, `amex`."
            ),
            keywords="credit card, card brands, visa, mastercard, amex, discover, jcb, discovery",
            relative_path=_TABLES_PATH,
            extra={
                # VGI414: retired `vgi.result_columns_md` migrated to the structured tag.
                "vgi.result_columns_schema": json.dumps(
                    [
                        {
                            "name": "brand",
                            "type": "VARCHAR",
                            "description": "A brand `card_brand()` can return, e.g. `visa`, `mastercard`, `amex`.",
                        }
                    ]
                ),
            },
        )
        examples = [
            FunctionExample(
                sql="SELECT count(*) AS brand_count FROM conform.main.card_brands()",
                description="Count the recognized card brands",
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


_POSTAL_COUNTRIES_SCHEMA = pa.schema(
    [field("country", pa.string(), "An ISO-3166 alpha-2 country code is_valid_postal_code accepts.", nullable=False)]
)


@init_single_worker
@bind_fixed_schema
class SupportedPostalCountriesFunction(TableFunctionGenerator[_NoArgs]):
    """The countries ``is_valid_postal_code(text, country)`` understands, one per row.

    ``country`` is exactly the value accepted as the second argument to
    ``is_valid_postal_code``; any other country makes that scalar raise, so read
    this table first to discover the supported set.
    """

    FIXED_SCHEMA: ClassVar[pa.Schema] = _POSTAL_COUNTRIES_SCHEMA

    class Meta:
        """Function metadata."""

        name = "supported_postal_countries"
        description = "The countries is_valid_postal_code() understands (US, CA, GB, DE, ...)"
        categories = ["conform", "postal"]
        tags = function_tags(
            title="List Supported Postal Countries",
            description_llm=(
                "## `supported_postal_countries()`\n\n"
                "A **table function** (no arguments) returning one row per country whose "
                "postal-code format `is_valid_postal_code(text, country)` can check, with a "
                "single column:\n\n"
                "- `country` (`VARCHAR`) -- an ISO-3166 alpha-2 code such as `US`, `CA`, "
                "`GB`, `DE`, `FR`, `NL`, `AU`, `JP`, `IN`, `BR`.\n\n"
                "Coverage is intentionally modest. Because `is_valid_postal_code` **raises** "
                "on an unsupported country (so a typo is not mistaken for an invalid code), "
                "read this table first -- or join against it -- to confirm a country is "
                "supported before calling the scalar."
            ),
            description_md=(
                "# `supported_postal_countries`\n\n"
                "Discovery table of every country `is_valid_postal_code()` can format-check.\n\n"
                "## Columns\n\n"
                "- `country` (`VARCHAR`) -- ISO-3166 alpha-2 code, e.g. `US`, `CA`, `GB`."
            ),
            keywords="postal code, zip code, postcode, countries, supported countries, country, discovery",
            relative_path=_TABLES_PATH,
            extra={
                "vgi.result_columns_schema": json.dumps(
                    [
                        {
                            "name": "country",
                            "type": "VARCHAR",
                            "description": (
                                "An ISO-3166 alpha-2 country code accepted as the `country` "
                                "argument to `is_valid_postal_code`."
                            ),
                        }
                    ]
                ),
            },
        )
        examples = [
            FunctionExample(
                sql="SELECT count(*) AS countries FROM conform.main.supported_postal_countries()",
                description="Count the supported postal-code countries",
            ),
            FunctionExample(
                sql=(
                    "SELECT count(*) > 0 AS supported "
                    "FROM conform.main.supported_postal_countries() WHERE country = 'US'"
                ),
                description="Check whether US postal codes are supported before validating",
            ),
        ]

    @classmethod
    def cardinality(cls, params: BindParams[_NoArgs]) -> TableCardinality:
        """Estimated and maximum row count for the planner."""
        return TableCardinality(estimate=10, max=100)

    @classmethod
    def process(cls, params: ProcessParams[_NoArgs], state: None, out: OutputCollector) -> None:
        """Emit one batch of discovery rows."""
        out.emit(
            pa.RecordBatch.from_pydict(
                {"country": validators.supported_postal_countries()},
                schema=params.output_schema,
            )
        )
        out.finish()


TABLE_FUNCTIONS: list[type] = [
    SupportedPhoneRegionsFunction,
    CardBrandsFunction,
    SupportedPostalCountriesFunction,
]
