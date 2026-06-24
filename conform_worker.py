# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python[http]>=0.8.4",
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

from vgi import Worker
from vgi.catalog import Catalog, Schema

from vgi_conform.scalars import SCALAR_FUNCTIONS
from vgi_conform.tables import TABLE_FUNCTIONS

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
    "Validation and normalization functions for email, phone, IBAN, VAT, credit-card, URL, and "
    "postal-code fields over Apache Arrow."
)

_CONFORM_CATALOG = Catalog(
    name="conform",
    default_schema="main",
    comment="Validate + normalize phone/email/IBAN/VAT/card/URL/postal fields for SQL",
    tags={
        "vgi.description_llm": _CATALOG_DESCRIPTION_LLM,
        "vgi.description_md": _CATALOG_DESCRIPTION_MD,
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
                "vgi.description_llm": _SCHEMA_DESCRIPTION_LLM,
                "vgi.description_md": _SCHEMA_DESCRIPTION_MD,
            },
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
