# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python[http]>=0.8.5",
#     "phonenumbers>=8.13",
#     "python-stdnum>=1.20",
#     "email-validator>=2.1",
# ]
# ///
"""VGI worker exposing field validation + normalization to SQL.

Assembles the conform functions in ``vgi_conform`` into a single ``conform``
catalog and runs the worker over stdio (DuckDB subprocess) or HTTP. It validates
AND normalizes real-world structured data fields -- phone, email, IBAN, VAT,
credit card, URL, postal code -- as DuckDB scalar functions, plus two discovery
table functions.

Usage:
    uv run conform_worker.py            # serve over stdio (DuckDB subprocess)

    INSTALL vgi FROM community; LOAD vgi;
    ATTACH 'conform' (TYPE vgi, LOCATION 'uv run conform_worker.py');

    SELECT conform.is_valid_email('a@b.com');                 -- true
    SELECT conform.normalize_email('Test@Example.COM');       -- 'test@example.com'
    SELECT conform.format_phone_e164('202-456-1111');         -- '+12024561111' (region 'US')
    SELECT conform.format_phone_e164('07911 123456', 'GB');   -- '+447911123456'
    SELECT conform.is_valid_iban('GB82 WEST 1234 5698 7654 32');
    SELECT conform.card_brand('4111111111111111');            -- 'visa'
    SELECT conform.mask_card('4111-1111-1111-1111');          -- '************1111'
    SELECT conform.normalize_url('HTTP://Example.com:80/Path');
    SELECT conform.is_valid_postal_code('90210', 'US');       -- true
    SELECT * FROM conform.supported_phone_regions();
    SELECT * FROM conform.card_brands();
"""

from __future__ import annotations

import json

from vgi import Worker
from vgi.catalog import Catalog, Schema, Table

from vgi_conform.meta import keywords_json
from vgi_conform.scalars import SCALAR_FUNCTIONS
from vgi_conform.tables import (
    TABLE_FUNCTIONS,
    CardBrandsFunction,
    SupportedPhoneRegionsFunction,
)

_FUNCTIONS: list[type] = [
    *SCALAR_FUNCTIONS,
    *TABLE_FUNCTIONS,
]

_CATALOG_DESCRIPTION_LLM = (
    "Validate and normalize real-world structured-data fields in SQL: email, phone number, IBAN, "
    "EU VAT number, credit-card number, URL, and postal code. Scalars test validity "
    "(`is_valid_email`, `is_valid_phone`, `is_valid_iban`, `is_valid_vat`, `is_valid_card`, "
    "`is_valid_url`, `is_valid_postal_code`), normalize/format values (`normalize_email`, "
    "`format_phone_e164`/`format_phone_national`/`format_phone_international`, `format_iban`, "
    "`format_vat`, `normalize_url`, `mask_card`), and extract parts (`email_domain`, "
    "`phone_region`, `phone_type`, `iban_country`, `card_brand`, `url_host`). Phone and VAT take an "
    "optional ISO region/country argument ('US' / EU-prefixed by default); postal code requires a "
    "country. Use for data-cleaning, validation, and standardization of contact, banking, and "
    "payment fields. Validation is offline and deterministic (no DNS or network)."
)

_CATALOG_DESCRIPTION_MD = (
    "# conform\n\n"
    "Validate **and** normalize real-world structured-data fields for DuckDB via VGI -- email, "
    "phone, IBAN, EU VAT, credit card, URL, and postal code -- backed by `phonenumbers`, "
    "`python-stdnum`, and `email-validator`. All validation is offline and deterministic.\n\n"
    "**Scalars:** `is_valid_email`, `normalize_email`, `email_domain`, `is_valid_phone`, "
    "`format_phone_e164`, `format_phone_national`, `format_phone_international`, `phone_region`, "
    "`phone_type`, `is_valid_iban`, `format_iban`, `iban_country`, `is_valid_vat`, `format_vat`, "
    "`is_valid_card`, `card_brand`, `mask_card`, `is_valid_url`, `normalize_url`, `url_host`, "
    "`is_valid_postal_code`.\n\n"
    "**Table functions:** `supported_phone_regions`, `card_brands`.\n\n"
    "Phone/VAT region and country are arguments; `'US'` / the EU-prefixed form are only defaults. "
    "See `conform.supported_phone_regions()` and `conform.card_brands()` for coverage."
)

_SCHEMA_DESCRIPTION_LLM = (
    "Field validation and normalization functions: validity tests, normalizers/formatters, and "
    "part extractors for email, phone, IBAN, EU VAT, credit-card, URL, and postal-code values, "
    "plus discovery tables of supported phone regions and card brands."
)

_SCHEMA_DESCRIPTION_MD = (
    "The `main` schema holds every conform function: validity tests "
    "(`is_valid_email`, `is_valid_phone`, `is_valid_iban`, `is_valid_vat`, `is_valid_card`, "
    "`is_valid_url`, `is_valid_postal_code`), normalizers/formatters (`normalize_email`, "
    "`format_phone_e164`/`_national`/`_international`, `format_iban`, `format_vat`, "
    "`normalize_url`, `mask_card`), and part extractors (`email_domain`, `phone_region`, "
    "`phone_type`, `iban_country`, `card_brand`, `url_host`) for email, phone, IBAN, EU VAT, "
    "credit-card, URL, and postal-code fields, plus the discovery tables "
    "`supported_phone_regions` and `card_brands`. All validation is offline and deterministic "
    "(no DNS or network). Use it to clean, validate, and standardize contact, banking, and "
    "payment data."
)

_SCHEMA_EXAMPLE_QUERIES = (
    "SELECT conform.main.is_valid_email('a@b.com');\n"
    "SELECT conform.main.normalize_email('Test@Example.COM');\n"
    "SELECT conform.main.format_phone_e164('202-456-1111');\n"
    "SELECT conform.main.is_valid_iban('GB82 WEST 1234 5698 7654 32');\n"
    "SELECT conform.main.card_brand('4111111111111111');\n"
    "SELECT conform.main.mask_card('4111-1111-1111-1111');\n"
    "SELECT conform.main.is_valid_postal_code('90210', 'US');\n"
    "SELECT * FROM conform.main.card_brands() ORDER BY brand;"
)


# VGI311: the discovery functions take no arguments, so they always return the
# same rows. Expose each as a regular table (function-backed -- DuckDB scans the
# matching table function) so consumers can write `SELECT * FROM conform.main.<name>`
# without parentheses, in addition to calling `<name>()`. The table's schema is
# derived from the function's bind(), so the two stay in lockstep. Each table
# carries the same discoverability tags as a function (VGI112/113/123/124/126) and
# declares its natural primary key (VGI807/VGI806).
_PHONE_REGIONS_DOC_LLM = (
    "## `supported_phone_regions` (table)\n\n"
    "One row per phone region the conform phone functions understand. Columns:\n\n"
    "- `region` (`VARCHAR`, primary key) -- the ISO-3166 alpha-2 code you pass as the optional "
    "`region` argument to `is_valid_phone(text, region)`, the phone formatters, `phone_region`, "
    "and `phone_type`.\n"
    "- `country_code` (`INTEGER`) -- its international dialling (country calling) code.\n\n"
    "Query it directly (`SELECT * FROM conform.main.supported_phone_regions`) to discover valid "
    "region values or look up a country's dialling code. Backed by the identically-named table "
    "function, so the rows are identical."
)

_PHONE_REGIONS_DOC_MD = (
    "# `supported_phone_regions`\n\n"
    "Discovery table of every phone region the worker understands, exposed as a regular table so "
    "you can `SELECT * FROM conform.main.supported_phone_regions` without parentheses.\n\n"
    "## Columns\n\n"
    "- `region` (VARCHAR, primary key) -- ISO-3166 alpha-2 region code (the optional `region` "
    "argument to the phone functions).\n"
    "- `country_code` (INTEGER) -- international dialling (country calling) code.\n\n"
    "## Usage\n\n"
    "```sql\n"
    "SELECT * FROM conform.main.supported_phone_regions ORDER BY region;\n"
    "```"
)

_CARD_BRANDS_DOC_LLM = (
    "## `card_brands` (table)\n\n"
    "One row per card brand the `card_brand` scalar can emit. Single column:\n\n"
    "- `brand` (`VARCHAR`, primary key) -- a brand name such as `visa`, `mastercard`, `amex`, "
    "`discover`, `diners`, `jcb`.\n\n"
    "Query it directly (`SELECT * FROM conform.main.card_brands`) to enumerate the recognized "
    "brands -- e.g. to populate a UI filter or validate that a `card_brand(...)` result is within "
    "the known set. Backed by the identically-named table function."
)

_CARD_BRANDS_DOC_MD = (
    "# `card_brands`\n\n"
    "Discovery table of every brand `card_brand()` can return, exposed as a regular table so you "
    "can `SELECT * FROM conform.main.card_brands` without parentheses.\n\n"
    "## Columns\n\n"
    "- `brand` (VARCHAR, primary key) -- e.g. `visa`, `mastercard`, `amex`, `discover`, `diners`, "
    "`jcb`.\n\n"
    "## Usage\n\n"
    "```sql\n"
    "SELECT * FROM conform.main.card_brands ORDER BY brand;\n"
    "```"
)

_DISCOVERY_TABLES: list[Table] = [
    Table(
        name="supported_phone_regions",
        function=SupportedPhoneRegionsFunction,
        comment="Every (region, country_code) the phone functions understand (discovery table).",
        primary_key=(("region",),),
        not_null=("region", "country_code"),
        column_comments={
            "region": "ISO-3166 alpha-2 region code (the optional `region` argument to the phone functions).",
            "country_code": "International dialling (country calling) code.",
        },
        tags={
            "vgi.title": "Supported Phone Regions Table",
            "vgi.doc_llm": _PHONE_REGIONS_DOC_LLM,
            "vgi.doc_md": _PHONE_REGIONS_DOC_MD,
            "vgi.keywords": keywords_json("phone, regions, supported regions, country code, dialling code, discovery"),
            "domain": "data-quality",
            "vgi.example_queries": json.dumps(
                [
                    {
                        "description": "List every supported phone region.",
                        "sql": "SELECT * FROM conform.main.supported_phone_regions ORDER BY region",
                    },
                    {
                        "description": "Look up the UK's international dialling code.",
                        "sql": "SELECT country_code FROM conform.main.supported_phone_regions WHERE region = 'GB'",
                    },
                ]
            ),
        },
    ),
    Table(
        name="card_brands",
        function=CardBrandsFunction,
        comment="The brands card_brand() can return, one per row (discovery table).",
        primary_key=(("brand",),),
        not_null=("brand",),
        column_comments={
            "brand": "A brand `card_brand()` can return, e.g. `visa`, `mastercard`, `amex`.",
        },
        tags={
            "vgi.title": "Recognized Card Brands Table",
            "vgi.doc_llm": _CARD_BRANDS_DOC_LLM,
            "vgi.doc_md": _CARD_BRANDS_DOC_MD,
            "vgi.keywords": keywords_json("credit card, card brands, visa, mastercard, amex, discover, jcb, discovery"),
            "domain": "data-quality",
            "vgi.example_queries": json.dumps(
                [
                    {
                        "description": "List every recognized card brand.",
                        "sql": "SELECT * FROM conform.main.card_brands ORDER BY brand",
                    },
                    {
                        "description": "Count how many card brands the worker recognizes.",
                        "sql": "SELECT count(*) AS brand_count FROM conform.main.card_brands",
                    },
                ]
            ),
        },
    ),
]


_CONFORM_CATALOG = Catalog(
    name="conform",
    default_schema="main",
    comment="Validate + normalize phone/email/IBAN/VAT/card/URL/postal fields for SQL",
    tags={
        "vgi.title": "Field Validation & Normalization (conform)",
        # VGI138: keywords must be a JSON array of strings, not comma-separated.
        "vgi.keywords": keywords_json(
            "validate, normalize, conform, data cleaning, data quality, email, phone, "
            "IBAN, VAT, credit card, URL, postal code, standardization"
        ),
        "vgi.doc_llm": _CATALOG_DESCRIPTION_LLM,
        "vgi.doc_md": _CATALOG_DESCRIPTION_MD,
        "vgi.author": "Query.Farm",
        "vgi.copyright": "Copyright 2026 Query Farm LLC - https://query.farm",
        "vgi.license": "MIT",
        "vgi.support_contact": "https://github.com/Query-farm/vgi-conform/issues",
        "vgi.support_policy_url": "https://github.com/Query-farm/vgi-conform/blob/main/README.md",
    },
    source_url="https://github.com/Query-farm/vgi-conform",
    schemas=[
        Schema(
            name="main",
            comment="Field validation, normalization, and discovery functions for the conform catalog",
            tags={
                "vgi.title": "Conform — main schema",
                # VGI138: keywords must be a JSON array of strings, not comma-separated.
                "vgi.keywords": keywords_json(
                    "validate, normalize, email, phone, IBAN, VAT, credit card, URL, "
                    "postal code, is_valid_email, format_phone_e164, mask_card, "
                    "supported_phone_regions, card_brands, data cleaning"
                ),
                # VGI123 classifying tags use BARE keys (not vgi.-namespaced).
                "domain": "data-quality",
                "category": "validation-and-normalization",
                "topic": "contact-banking-payment-fields",
                # VGI139: per-object vgi.source_url dropped; source_url lives on the
                # catalog object (the Catalog(source_url=...) argument) only.
                "vgi.doc_llm": _SCHEMA_DESCRIPTION_LLM,
                "vgi.doc_md": _SCHEMA_DESCRIPTION_MD,
                # VGI506 representative, catalog-qualified example queries.
                "vgi.example_queries": _SCHEMA_EXAMPLE_QUERIES,
            },
            tables=list(_DISCOVERY_TABLES),
            functions=list(_FUNCTIONS),
        ),
    ],
)


class ConformWorker(Worker):
    """Worker process hosting the ``conform`` catalog."""

    catalog = _CONFORM_CATALOG


def main() -> None:
    """Run the conform worker process (stdio or, via flags, HTTP)."""
    ConformWorker.main()


if __name__ == "__main__":
    main()
