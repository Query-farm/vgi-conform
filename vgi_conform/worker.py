"""VGI worker exposing field validation + normalization to SQL.

Assembles the conform functions in ``vgi_conform`` into a single ``conform``
catalog and runs the worker over stdio (DuckDB subprocess) or HTTP. It validates
AND normalizes real-world structured data fields -- phone, email, IBAN, VAT,
credit card, URL, postal code -- as DuckDB scalar functions, plus three discovery
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
from collections import defaultdict

from vgi import Worker
from vgi.catalog import Catalog, Schema, Table
from vgi.metadata import FunctionExample

from vgi_conform.meta import keywords_json
from vgi_conform.scalars import SCALAR_FUNCTIONS
from vgi_conform.tables import (
    TABLE_FUNCTIONS,
    CardBrandsFunction,
    SupportedPhoneRegionsFunction,
    SupportedPostalCountriesFunction,
)

_FUNCTIONS: list[type] = [
    *SCALAR_FUNCTIONS,
    *TABLE_FUNCTIONS,
]

# VGI411: every object in a schema that declares categories must carry a
# `vgi.category`. Each function's `Meta.categories` second element already names its
# family (email/phone/iban/vat/card/url/postal); mirror it into the per-object
# `vgi.category` tag so the schema registry (_CATEGORIES_JSON) and its members stay
# in lockstep. (The three discovery tables set `vgi.category` inline below.)
for _fn in _FUNCTIONS:
    _fn.Meta.tags["vgi.category"] = _fn.Meta.categories[1]  # type: ignore[attr-defined]

# VGI515: `vgi.example_queries` must be a JSON list of {description, sql} objects so
# every example carries a human-readable description. Each function already declares
# `Meta.examples` (FunctionExample(sql, description)) as its single source of truth --
# used for native `duckdb_functions().examples` and for --execute coverage. Mirror
# those into the tag as a described list so the community extension does not fall back
# to synthesizing a bare, description-less SQL blob for the tag.
#
# Arity-overloaded scalars (e.g. `is_valid_phone(text)` and `is_valid_phone(text,
# region)`) are separate classes sharing one `Meta.name`. The extension unions their
# tags into a single catalog entry AND surfaces every overload's `Meta.examples` into
# the one native examples column. So the tag must carry EVERY overload's examples
# (aggregated by name); otherwise the un-tagged overload's native example survives the
# tag/native merge as a description-less entry and trips VGI515.
_EXAMPLES_BY_NAME: dict[str, list[FunctionExample]] = defaultdict(list)
for _fn in _FUNCTIONS:
    for _ex in getattr(_fn.Meta, "examples", []):  # type: ignore[attr-defined]
        _EXAMPLES_BY_NAME[_fn.Meta.name].append(_ex)  # type: ignore[attr-defined]

for _fn in _FUNCTIONS:
    _seen_sql: set[str] = set()
    _described: list[dict[str, str]] = []
    for _ex in _EXAMPLES_BY_NAME.get(_fn.Meta.name, []):  # type: ignore[attr-defined]
        _key = " ".join(_ex.sql.split()).lower()
        if _key in _seen_sql:
            continue
        _seen_sql.add(_key)
        _described.append({"description": _ex.description, "sql": _ex.sql})
    if _described:
        _fn.Meta.tags["vgi.example_queries"] = json.dumps(_described)  # type: ignore[attr-defined]

_CATALOG_DESCRIPTION_LLM = (
    "Validate and normalize real-world structured-data fields directly in SQL -- email addresses, "
    "phone numbers, IBANs, EU VAT numbers, credit-card numbers, URLs, and postal codes.\n\n"
    "This worker turns the data-cleaning steps you would normally script in Python into set-based "
    "DuckDB functions: check whether a value is well-formed, rewrite it into a canonical form for "
    "joining/deduplication, or pull out a part (a domain, a country, a brand). Reach for it "
    "whenever a table holds messy contact, banking, or payment fields that must be filtered, "
    "standardized, or bucketed before use.\n\n"
    "Two ideas run through the whole surface. First, every operation is offline and deterministic "
    "-- validation checks syntax, structure, and checksums (mod-97 for IBAN, Luhn for cards, "
    "per-country rules for VAT and postal codes) but never performs a DNS or network lookup, so it "
    "is safe over huge tables. Second, outcomes are total and predictable: NULL input yields NULL "
    "output; an invalid non-NULL value yields false from a validity test and NULL from a formatter "
    "or extractor -- nothing raises (the one deliberate exception is an unknown postal-code "
    "country, which errors so a typo is not mistaken for an invalid code).\n\n"
    "Phone and VAT operations accept an optional ISO region/country argument (US and the "
    "EU-prefixed form are the defaults); postal-code validation requires an explicit country."
)

_CATALOG_DESCRIPTION_MD = (
    "# conform: Field Validation & Normalization in SQL\n\n"
    "**Validate and normalize phone numbers, emails, IBANs, EU VAT numbers, credit-card numbers, "
    "URLs, and postal codes directly in DuckDB SQL** -- no UDF plumbing, no external service, and "
    "no network calls. The `conform` extension turns the data-cleaning steps you would normally "
    "script in Python into fast, set-based SQL functions, so you can check validity, standardize "
    "formatting, and extract field parts right where your data lives.\n\n"
    "This catalog is built for anyone wrangling messy real-world contact, banking, and payment "
    "data: data engineers cleaning a CRM export, analysts deduplicating customer records, or "
    "pipelines that must reject malformed input before it lands. Every check is **offline, "
    "deterministic, and total** -- functions never raise on garbage (with one deliberate "
    "exception, an unknown postal-code country), returning `false` for `is_valid_*` and `NULL` for "
    "formatters and extractors. That makes the extension hermetic and safe to run over huge tables "
    "without DNS lookups or flaky I/O.\n\n"
    "Under the hood, `conform` composes three best-in-class, battle-tested libraries. Phone "
    "parsing, validation, and E.164/national/international formatting come from "
    "[`phonenumbers`](https://github.com/daviddrysdale/python-phonenumbers) (the Python port of "
    "Google's [libphonenumber](https://github.com/google/libphonenumber)). IBAN, EU VAT, and the "
    "Luhn credit-card check come from [`python-stdnum`]"
    "(https://github.com/arthurdejong/python-stdnum) "
    "([documentation](https://arthurdejong.org/python-stdnum/)). Email syntax validation and "
    "normalization come from [`email-validator`]"
    "(https://github.com/JoshData/python-email-validator). URL and postal-code handling are "
    "implemented in-process against per-country rules.\n\n"
    "## What you get\n\n"
    "The surface divides into three shapes -- **validity tests** that return a boolean, "
    "**normalizers/formatters** that rewrite a value into a canonical string (ideal for joining or "
    "deduplication), and **part extractors** that pull a single component (a domain, country, "
    "brand, or host) out of a well-formed value -- plus discovery tables that enumerate "
    "the phone regions and card brands the worker recognizes.\n\n"
    "Phone and VAT functions take an optional ISO region/country argument (`'US'` and the "
    "EU-prefixed form are defaults); postal-code validation requires a country.\n\n"
    "```sql\n"
    "SELECT conform.main.normalize_email('Test@Example.COM');\n"
    "SELECT conform.main.format_phone_e164('07911 123456', 'GB');\n"
    "SELECT conform.main.mask_card('4111-1111-1111-1111');\n"
    "```"
)

_SCHEMA_DESCRIPTION_LLM = (
    "Field-level validation, normalization, and extraction for the conform catalog; everything "
    "lives in this single `main` schema.\n\n"
    "Functions come in three shapes. Validity tests return `BOOLEAN` (true/false, NULL on NULL "
    "input). Normalizers and formatters return a canonical `VARCHAR` -- a form suitable for storage, "
    "joining, or deduplication -- or NULL when the input is invalid. Part extractors pull a single "
    "component (such as a domain, country code, or card brand) out of a well-formed value. Two "
    "discovery tables enumerate the phone regions and card brands the worker recognizes.\n\n"
    "The fields covered are email, phone, IBAN, EU VAT, credit card, URL, and postal code. All "
    "validation is offline and deterministic (no DNS or network). Phone and VAT accept an optional "
    "ISO region/country; postal-code checks require a country. Use this schema to clean, validate, "
    "and standardize contact, banking, and payment data."
)

_SCHEMA_DESCRIPTION_MD = (
    "# conform · main schema\n\n"
    "Field validation, normalization, and extraction for email, phone, IBAN, EU VAT, credit-card, "
    "URL, and postal-code values, plus three discovery tables.\n\n"
    "## What's here\n\n"
    "The functions come in three shapes:\n\n"
    "- **Validity tests** return `BOOLEAN` -- `true`/`false`, and `NULL` on `NULL` input.\n"
    "- **Normalizers & formatters** return a canonical `VARCHAR` for storage, joining, or "
    "deduplication, or `NULL` for invalid input.\n"
    "- **Part extractors** pull one component (a domain, country code, brand, or host) out of a "
    "well-formed value.\n\n"
    "Two discovery tables enumerate the phone regions and card brands the worker recognizes.\n\n"
    "## Conventions\n\n"
    "All validation is **offline and deterministic** -- no DNS or network. Phone and VAT functions "
    "accept an optional ISO region/country argument; postal-code checks require a country."
)

# VGI515: vgi.example_queries must be a JSON list of {description, sql} objects so
# every example carries a human-readable description.
_SCHEMA_EXAMPLE_QUERIES = json.dumps(
    [
        {
            "description": "Check whether a string is a syntactically valid email address.",
            "sql": "SELECT conform.main.is_valid_email('a@b.com')",
        },
        {
            "description": "Canonicalize an email address (lower-cased domain) for deduplication.",
            "sql": "SELECT conform.main.normalize_email('Test@Example.COM')",
        },
        {
            "description": "Format a US phone number into canonical E.164 storage form.",
            "sql": "SELECT conform.main.format_phone_e164('202-456-1111')",
        },
        {
            "description": "Validate an IBAN (length plus mod-97 checksum).",
            "sql": "SELECT conform.main.is_valid_iban('GB82 WEST 1234 5698 7654 32')",
        },
        {
            "description": "Detect a payment card's brand from its prefix and length.",
            "sql": "SELECT conform.main.card_brand('4111111111111111')",
        },
        {
            "description": "Mask a card number, keeping only the last four digits.",
            "sql": "SELECT conform.main.mask_card('4111-1111-1111-1111')",
        },
        {
            "description": "Format-check a US postal (ZIP) code.",
            "sql": "SELECT conform.main.is_valid_postal_code('90210', 'US')",
        },
        {
            "description": "List every recognized payment-card brand.",
            "sql": "SELECT * FROM conform.main.card_brands() ORDER BY brand",
        },
    ]
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
    "Read this table directly to discover valid region values or to look up a country's dialling "
    "code. Backed by the identically-named table function, so the rows are identical."
)

_PHONE_REGIONS_DOC_MD = (
    "# `supported_phone_regions`\n\n"
    "Discovery table of every phone region the worker understands, exposed as a regular table you "
    "can read without parentheses.\n\n"
    "## Columns\n\n"
    "- `region` (`VARCHAR`, primary key) -- ISO-3166 alpha-2 region code (the optional `region` "
    "argument to the phone functions).\n"
    "- `country_code` (`INTEGER`) -- international dialling (country calling) code.\n\n"
    "Read it directly to discover valid region values or look up a dialling code; see the "
    "table's example queries for ready-to-run SQL."
)

_CARD_BRANDS_DOC_LLM = (
    "## `card_brands` (table)\n\n"
    "One row per card brand the `card_brand` scalar can emit. Single column:\n\n"
    "- `brand` (`VARCHAR`, primary key) -- a brand name such as `visa`, `mastercard`, `amex`, "
    "`discover`, `diners`, `jcb`.\n\n"
    "Read this table directly to enumerate the recognized brands -- e.g. to populate a UI filter "
    "or to validate that a `card_brand(...)` result is within the known set. Backed by the "
    "identically-named table function."
)

_POSTAL_COUNTRIES_DOC_LLM = (
    "## `supported_postal_countries` (table)\n\n"
    "One row per country whose postal-code format `is_valid_postal_code(text, country)` can "
    "check. Single column:\n\n"
    "- `country` (`VARCHAR`, primary key) -- the ISO-3166 alpha-2 code you pass as the `country` "
    "argument to `is_valid_postal_code` (e.g. `US`, `CA`, `GB`, `DE`).\n\n"
    "Coverage is intentionally modest. Because `is_valid_postal_code` **raises** on an "
    "unsupported country, read (or join against) this table to confirm a country is supported "
    "before validating. Backed by the identically-named table function."
)

_POSTAL_COUNTRIES_DOC_MD = (
    "# `supported_postal_countries`\n\n"
    "Discovery table of every country `is_valid_postal_code()` can format-check, exposed as a "
    "regular table you can read without parentheses.\n\n"
    "## Columns\n\n"
    "- `country` (`VARCHAR`, primary key) -- ISO-3166 alpha-2 code, e.g. `US`, `CA`, `GB`.\n\n"
    "Read it directly to discover the supported countries before calling "
    "`is_valid_postal_code(text, country)`."
)

_CARD_BRANDS_DOC_MD = (
    "# `card_brands`\n\n"
    "Discovery table of every brand `card_brand()` can return, exposed as a regular table you can "
    "read without parentheses.\n\n"
    "## Columns\n\n"
    "- `brand` (`VARCHAR`, primary key) -- e.g. `visa`, `mastercard`, `amex`, `discover`, `diners`, "
    "`jcb`.\n\n"
    "Read it directly to enumerate the recognized brands; see the table's example queries for "
    "ready-to-run SQL."
)

# VGI413/VGI408: the schema's category registry (an ordered JSON array; array
# order is the display order). Every object carries a `vgi.category` naming one of
# these slugs (wired up below), so the categories drive complete navigation/SEO and
# no category is left empty (VGI411/VGI412).
_CATEGORIES_JSON = json.dumps(
    [
        {
            "name": "email",
            "title": "Email",
            "description": "Validate, normalize, and extract parts of email addresses.",
        },
        {
            "name": "phone",
            "title": "Phone",
            "description": "Validate, format, and classify phone numbers; discover supported regions.",
        },
        {
            "name": "iban",
            "title": "IBAN",
            "description": "Validate, pretty-print, and extract the country of bank IBANs.",
        },
        {
            "name": "vat",
            "title": "EU VAT",
            "description": "Validate and normalize EU VAT numbers.",
        },
        {
            "name": "card",
            "title": "Payment Card",
            "description": "Luhn-check, brand-detect, and mask credit-card numbers; list known brands.",
        },
        {
            "name": "url",
            "title": "URL",
            "description": "Validate, normalize, and extract the host of web URLs.",
        },
        {
            "name": "postal",
            "title": "Postal Code",
            "description": "Format-check postal codes for supported countries.",
        },
    ]
)

# VGI152/VGI407: the agent-suitability suite (`vgi-lint simulate`). Each task is a
# {name, prompt} object; `reference_sql` is a grader-only canonical solution and is
# never shown to the analyst. Prompts are natural-language and self-contained; every
# reference matches a documented example, so the suite is sound and deterministic.
# Each task answers with a single scalar value, so grading compares VALUES only
# (`ignore_column_names`) -- the analyst's auto-generated column label need not
# match the reference's.
_AGENT_TEST_TASKS_JSON = json.dumps(
    [
        # --- email ---
        {
            "name": "validate-email",
            "prompt": "Is 'a@b.com' a syntactically valid email address? Return the boolean.",
            "reference_sql": "SELECT conform.main.is_valid_email('a@b.com')",
            "ignore_column_names": True,
        },
        {
            "name": "normalize-email",
            "prompt": "Normalize the email address 'Test@Example.COM' to its canonical form.",
            "reference_sql": "SELECT conform.main.normalize_email('Test@Example.COM')",
            "ignore_column_names": True,
        },
        {
            "name": "email-domain",
            "prompt": "Extract just the domain part of the email address 'a@Example.com'.",
            "reference_sql": "SELECT conform.main.email_domain('a@Example.com')",
            "ignore_column_names": True,
        },
        # --- phone ---
        {
            "name": "validate-phone-us",
            "prompt": "Is '202-456-1111' a valid US phone number? Return the boolean.",
            "reference_sql": "SELECT conform.main.is_valid_phone('202-456-1111')",
            "ignore_column_names": True,
        },
        {
            "name": "phone-e164-gb",
            "prompt": "Format the UK phone number '07911 123456' as a canonical E.164 string.",
            "reference_sql": "SELECT conform.main.format_phone_e164('07911 123456', 'GB')",
            "ignore_column_names": True,
        },
        {
            "name": "phone-national-us",
            "prompt": "Format the US phone number '2024561111' in national display form.",
            "reference_sql": "SELECT conform.main.format_phone_national('2024561111')",
            "ignore_column_names": True,
        },
        {
            "name": "phone-international-us",
            "prompt": "Format the US phone number '202-456-1111' in international display form.",
            "reference_sql": "SELECT conform.main.format_phone_international('202-456-1111')",
            "ignore_column_names": True,
        },
        {
            "name": "phone-region",
            "prompt": "Which ISO region does the phone number '+12024561111' belong to?",
            "reference_sql": "SELECT conform.main.phone_region('+12024561111')",
            "ignore_column_names": True,
        },
        {
            "name": "phone-type-gb-mobile",
            "prompt": "What line type is the UK phone number '07911 123456' (parsed for the UK)?",
            "reference_sql": "SELECT conform.main.phone_type('07911 123456', 'GB')",
            "ignore_column_names": True,
        },
        {
            "name": "phone-regions-gb-dialling-code",
            "prompt": (
                "Using the worker's list of supported phone regions, what is the United Kingdom's "
                "international dialling (country calling) code?"
            ),
            "reference_sql": ("SELECT country_code FROM conform.main.supported_phone_regions() WHERE region = 'GB'"),
            "ignore_column_names": True,
        },
        # --- iban ---
        {
            "name": "validate-iban",
            "prompt": "Check whether 'GB82 WEST 1234 5698 7654 32' is a valid IBAN. Return the boolean.",
            "reference_sql": "SELECT conform.main.is_valid_iban('GB82 WEST 1234 5698 7654 32')",
            "ignore_column_names": True,
        },
        {
            "name": "format-iban",
            "prompt": "Pretty-print the IBAN 'GB82WEST12345698765432' into space-separated blocks of four.",
            "reference_sql": "SELECT conform.main.format_iban('GB82WEST12345698765432')",
            "ignore_column_names": True,
        },
        {
            "name": "iban-country",
            "prompt": "Which country does the IBAN 'DE89370400440532013000' belong to? Return the two-letter code.",
            "reference_sql": "SELECT conform.main.iban_country('DE89370400440532013000')",
            "ignore_column_names": True,
        },
        # --- vat ---
        {
            "name": "validate-vat",
            "prompt": "Is 'DE136695976' a valid country-prefixed EU VAT number? Return the boolean.",
            "reference_sql": "SELECT conform.main.is_valid_vat('DE136695976')",
            "ignore_column_names": True,
        },
        {
            "name": "format-vat",
            "prompt": "Normalize the EU VAT number 'DE 136 695 976' to its compact canonical form.",
            "reference_sql": "SELECT conform.main.format_vat('DE 136 695 976')",
            "ignore_column_names": True,
        },
        # --- card ---
        {
            "name": "validate-card-luhn",
            "prompt": "Does the card number '4111 1111 1111 1111' pass the Luhn checksum? Return the boolean.",
            "reference_sql": "SELECT conform.main.is_valid_card('4111 1111 1111 1111')",
            "ignore_column_names": True,
        },
        {
            "name": "card-brand",
            "prompt": "What payment-card brand is the number '4111111111111111'?",
            "reference_sql": "SELECT conform.main.card_brand('4111111111111111')",
            "ignore_column_names": True,
        },
        {
            "name": "mask-card",
            "prompt": "Mask the card number '4111-1111-1111-1111', keeping only the last four digits visible.",
            "reference_sql": "SELECT conform.main.mask_card('4111-1111-1111-1111')",
            "ignore_column_names": True,
        },
        {
            "name": "card-brands-count",
            "prompt": "How many distinct payment-card brands does the worker recognize?",
            "reference_sql": "SELECT count(*) FROM conform.main.card_brands()",
            "ignore_column_names": True,
        },
        # --- url ---
        {
            "name": "validate-url",
            "prompt": "Is 'https://example.com/path' a valid absolute URL? Return the boolean.",
            "reference_sql": "SELECT conform.main.is_valid_url('https://example.com/path')",
            "ignore_column_names": True,
        },
        {
            "name": "normalize-url",
            "prompt": "Normalize the URL 'HTTP://Example.com:80/Path' to its canonical form.",
            "reference_sql": "SELECT conform.main.normalize_url('HTTP://Example.com:80/Path')",
            "ignore_column_names": True,
        },
        {
            "name": "url-host",
            "prompt": "Extract the host (domain) from the URL 'https://WWW.Example.com/a'.",
            "reference_sql": "SELECT conform.main.url_host('https://WWW.Example.com/a')",
            "ignore_column_names": True,
        },
        # --- postal ---
        {
            "name": "postal-us",
            "prompt": "Is '90210' a well-formed United States postal code? Return the boolean.",
            "reference_sql": "SELECT conform.main.is_valid_postal_code('90210', 'US')",
            "ignore_column_names": True,
        },
        {
            "name": "postal-countries-count",
            "prompt": "How many countries does the worker's postal-code validator support?",
            "reference_sql": "SELECT count(*) FROM conform.main.supported_postal_countries()",
            "ignore_column_names": True,
        },
    ]
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
            "vgi.category": "phone",
            "domain": "data-quality",
            "vgi.example_queries": json.dumps(
                [
                    {
                        "description": "Count the supported regions and the distinct dialling codes among them.",
                        "sql": (
                            "SELECT count(*) AS regions, count(DISTINCT country_code) AS dialling_codes "
                            "FROM conform.main.supported_phone_regions"
                        ),
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
        name="supported_postal_countries",
        function=SupportedPostalCountriesFunction,
        comment="Every country is_valid_postal_code() understands, one per row (discovery table).",
        primary_key=(("country",),),
        not_null=("country",),
        column_comments={
            "country": "ISO-3166 alpha-2 country code accepted as the `country` argument to `is_valid_postal_code`.",
        },
        tags={
            "vgi.title": "Supported Postal Countries Table",
            "vgi.doc_llm": _POSTAL_COUNTRIES_DOC_LLM,
            "vgi.doc_md": _POSTAL_COUNTRIES_DOC_MD,
            "vgi.keywords": keywords_json(
                "postal code, zip code, postcode, countries, supported countries, country, discovery"
            ),
            "vgi.category": "postal",
            "domain": "data-quality",
            "vgi.example_queries": json.dumps(
                [
                    {
                        "description": "List every supported postal-code country in order.",
                        "sql": "SELECT country FROM conform.main.supported_postal_countries ORDER BY country",
                    },
                    {
                        "description": "Confirm US postal codes are supported before validating.",
                        "sql": (
                            "SELECT count(*) > 0 AS supported "
                            "FROM conform.main.supported_postal_countries WHERE country = 'US'"
                        ),
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
            "vgi.category": "card",
            "domain": "data-quality",
            "vgi.example_queries": json.dumps(
                [
                    {
                        "description": "Check whether 'visa' is among the recognized card brands.",
                        "sql": "SELECT count(*) > 0 AS has_visa FROM conform.main.card_brands WHERE brand = 'visa'",
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
        # VGI152/VGI407: agent-suitability suite (grader-only reference_sql per task).
        "vgi.agent_test_tasks": _AGENT_TEST_TASKS_JSON,
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
                # VGI413/VGI408: the schema's ordered category registry.
                "vgi.categories": _CATEGORIES_JSON,
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
