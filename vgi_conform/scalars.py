"""Per-row scalar conform functions.

Every function here is a true DuckDB **scalar** -- one value (per row) in, one
value out -- so it can be used inline in any projection or predicate:

    SELECT is_valid_email(email)                 FROM users;
    SELECT id, normalize_email(email)            FROM users;
    SELECT format_phone_e164(phone, 'GB')        FROM contacts;
    SELECT mask_card(pan)                         FROM payments;

A note on argument syntax
-------------------------
VGI / DuckDB *scalar* functions take **positional** arguments and resolve
overloads by *arity* (the ``name := value`` named-argument syntax is a property
of table functions and macros, not scalars). The optional ``region`` / ``country``
arguments therefore cannot have Python-style defaults on a single class; instead
each optional trailing argument is exposed as its own arity overload that shares
the function ``name`` -- the same idiom the sibling ``vgi-calendar`` worker uses
for ``is_holiday(date)`` / ``is_holiday(date, country)``. So, e.g.:

    is_valid_phone(text)            -- region defaults to 'US'
    is_valid_phone(text, region)    -- explicit region

NULL semantics: a NULL input row yields NULL output (predicates included);
formatters / extractors yield NULL on invalid input; ``is_valid_*`` yields
``false`` on invalid (non-NULL) input.

Set-returning discovery functions (``supported_phone_regions``, ``card_brands``)
live in :mod:`vgi_conform.tables`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Annotated

import pyarrow as pa
from vgi.arguments import ConstParam, Param, Returns
from vgi.metadata import FunctionExample
from vgi.scalar_function import ScalarFunction

from . import validators
from .meta import function_tags

_DEFAULT_REGION = "US"

_SCALARS_PATH = "vgi_conform/scalars.py"

# VGI509: a JSON list of guaranteed-runnable, self-contained, catalog-qualified
# examples attached to (at least) one object. These exercise only offline scalars
# (no external service), so the linter can execute them as written against an
# attached worker. ``expected_result`` is intentionally omitted (optional).
_EXECUTABLE_EXAMPLES_JSON = json.dumps(
    [
        {
            "description": "Mask all but the last four digits of a card number.",
            "sql": "SELECT conform.main.mask_card('4111-1111-1111-1111')",
        },
        {
            "description": "Detect a card's brand from its prefix and length.",
            "sql": "SELECT conform.main.card_brand('4111111111111111')",
        },
        {
            "description": "Validate a card number against the Luhn checksum.",
            "sql": "SELECT conform.main.is_valid_card('4111 1111 1111 1111')",
        },
        {
            "description": "Normalize an email address (lower-cased domain).",
            "sql": "SELECT conform.main.normalize_email('Test@Example.COM')",
        },
        {
            "description": "Format a US phone number as canonical E.164.",
            "sql": "SELECT conform.main.format_phone_e164('202-456-1111')",
        },
    ]
)


# ---------------------------------------------------------------------------
# Small mapping helpers: apply a pure ``str -> X`` function across an array,
# passing NULL straight through.
# ---------------------------------------------------------------------------


def _map_bool(arr: pa.StringArray, fn: Callable[[str], bool]) -> pa.BooleanArray:
    out = [None if x is None else fn(x) for x in arr.to_pylist()]
    return pa.array(out, type=pa.bool_())


def _map_str(arr: pa.StringArray, fn: Callable[[str], str | None]) -> pa.StringArray:
    out = [None if x is None else fn(x) for x in arr.to_pylist()]
    return pa.array(out, type=pa.string())


# ===========================================================================
# Email -- no region/country argument.
# ===========================================================================


class IsValidEmailFunction(ScalarFunction):
    """``is_valid_email(text)`` -- True if syntactically valid (no DNS check)."""

    class Meta:
        """Function metadata."""

        name = "is_valid_email"
        description = "True if text is a syntactically valid email address (no DNS lookup)"
        categories = ["conform", "email"]
        tags = function_tags(
            title="Is Valid Email Address",
            description_llm=(
                "## `is_valid_email(text)`\n\n"
                "Returns `BOOLEAN`: `true` when `text` is a **syntactically** valid email "
                "address, `false` when it is not, and `NULL` when `text` is `NULL`.\n\n"
                "Validation is **offline** -- it checks address syntax and normalizes the "
                "domain, but performs **no DNS or deliverability lookup**, so it is fast, "
                "deterministic, and never makes a network call.\n\n"
                "Use it to gate or filter a column of user-supplied email values "
                "(`WHERE conform.is_valid_email(email)`), or as a quality check before "
                "loading contact data. Pair with `normalize_email` to canonicalize the "
                "values you keep."
            ),
            description_md=(
                "# `is_valid_email`\n\n"
                "Test whether a string is a syntactically valid email address.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.is_valid_email('a@b.com');   -- true\n"
                "SELECT conform.is_valid_email('not-email');  -- false\n"
                "```\n\n"
                "## Notes\n\n"
                "- Offline only -- no DNS / deliverability check.\n"
                "- `NULL` in yields `NULL` out; any non-`NULL` invalid value yields `false`."
            ),
            keywords="email, e-mail, validate email, is valid email, email syntax, address check",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(sql="SELECT conform.is_valid_email('a@b.com')", description="Valid email"),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Email address to validate.")]
    ) -> Annotated[pa.BooleanArray, Returns()]:
        """Map each input row to its output value."""
        return _map_bool(text, validators.is_valid_email)


class NormalizeEmailFunction(ScalarFunction):
    """``normalize_email(text)`` -- normalized email, or NULL if invalid."""

    class Meta:
        """Function metadata."""

        name = "normalize_email"
        description = "Normalized email address (lower-cased domain, etc.), or NULL if invalid"
        categories = ["conform", "email"]
        tags = function_tags(
            title="Normalize Email Address",
            description_llm=(
                "## `normalize_email(text)`\n\n"
                "Returns `VARCHAR`: a **canonical** form of the email address (the domain "
                "lower-cased and IDNA-normalized; the local-part case left intact per the "
                "email standard), or `NULL` when `text` is invalid or `NULL`.\n\n"
                "Validation is offline (no DNS). Use this before grouping, joining, or "
                "deduplicating on email so that `Test@Example.COM` and `test@example.com` "
                "collapse to the same key. Combine with `is_valid_email` if you also need a "
                "validity flag."
            ),
            description_md=(
                "# `normalize_email`\n\n"
                "Canonicalize an email address for comparison / deduplication.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.normalize_email('Test@Example.COM');  -- 'Test@example.com'\n"
                "```\n\n"
                "## Notes\n\n"
                "- Lower-cases the domain; leaves the local-part case unchanged.\n"
                "- Returns `NULL` for invalid or `NULL` input."
            ),
            keywords="email, normalize email, canonical email, lowercase domain, dedupe email",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.normalize_email('Test@Example.COM')",
                description="Normalize an email address",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Email address to normalize.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, validators.normalize_email)


class EmailDomainFunction(ScalarFunction):
    """``email_domain(text)`` -- the domain part, or NULL if invalid."""

    class Meta:
        """Function metadata."""

        name = "email_domain"
        description = "The (normalized) domain part of an email address, or NULL if invalid"
        categories = ["conform", "email"]
        tags = function_tags(
            title="Extract Email Domain",
            description_llm=(
                "## `email_domain(text)`\n\n"
                "Returns `VARCHAR`: the **domain** portion (everything after the `@`), "
                "lower-cased / normalized, of a valid email address; `NULL` for invalid or "
                "`NULL` input.\n\n"
                "Use it to group or count addresses by provider/organization "
                "(`GROUP BY conform.email_domain(email)`), spot disposable-domain patterns, "
                "or route by domain. Offline -- no DNS."
            ),
            description_md=(
                "# `email_domain`\n\n"
                "Extract the (normalized) domain part of an email address.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.email_domain('a@Example.com');  -- 'example.com'\n"
                "```\n\n"
                "## Notes\n\n"
                "- Returns `NULL` when the address is invalid or `NULL`."
            ),
            keywords="email, domain, email domain, host, provider, group by domain",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.email_domain('a@Example.com')",
                description="Extract the email domain",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Email address.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, validators.email_domain)


# ===========================================================================
# Phone -- region overloads (default 'US').
# ===========================================================================


class IsValidPhoneFunction(ScalarFunction):
    """``is_valid_phone(text)`` -- valid phone parsed as US."""

    class Meta:
        """Function metadata."""

        name = "is_valid_phone"
        description = "True if text is a valid phone number (region defaults to 'US')"
        categories = ["conform", "phone"]
        tags = function_tags(
            title="Is Valid Phone Number",
            description_llm=(
                "## `is_valid_phone(text)`\n\n"
                "Returns `BOOLEAN`: `true` when `text` parses as a valid phone number with "
                "the parse region defaulting to `'US'`, `false` when it does not, `NULL` "
                "when `text` is `NULL`.\n\n"
                "Backed by Google's `libphonenumber` (via `phonenumbers`): the number must "
                "both parse and pass `is_valid_number`, so a parseable-but-bogus number is "
                "still `false`. Offline and deterministic.\n\n"
                "Use the two-argument overload `is_valid_phone(text, region)` to parse "
                "non-US numbers (e.g. `'GB'`)."
            ),
            description_md=(
                "# `is_valid_phone`\n\n"
                "Validate a phone number, parsing it as US by default.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.is_valid_phone('202-456-1111');         -- true\n"
                "SELECT conform.is_valid_phone('07911 123456', 'GB');   -- region overload\n"
                "```\n\n"
                "## Notes\n\n"
                "- Default parse region is `'US'`; pass a region for other countries.\n"
                "- Requires a parseable **and** valid number."
            ),
            keywords="phone, telephone, validate phone, is valid phone, phone number, libphonenumber",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.is_valid_phone('202-456-1111')",
                description="Validate a US phone number",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Phone number to validate.")]
    ) -> Annotated[pa.BooleanArray, Returns()]:
        """Map each input row to its output value."""
        return _map_bool(text, lambda x: validators.is_valid_phone(x, _DEFAULT_REGION))


class IsValidPhoneRegionFunction(ScalarFunction):
    """``is_valid_phone(text, region)`` -- valid phone parsed as ``region``."""

    class Meta:
        """Function metadata."""

        name = "is_valid_phone"
        description = "True if text is a valid phone number in a given region"
        categories = ["conform", "phone"]
        tags = function_tags(
            title="Is Valid Phone Number In Region",
            description_llm=(
                "## `is_valid_phone(text, region)`\n\n"
                "Returns `BOOLEAN`: `true` when `text` parses as a valid phone number using "
                "`region` (an ISO-3166 alpha-2 code such as `'GB'`, `'DE'`, `'IN'`) as the "
                "parse/default region, `false` when it does not, `NULL` when `text` is "
                "`NULL`.\n\n"
                "This is the explicit-region overload of `is_valid_phone`; use it whenever "
                "the numbers are not US-format. The `region` argument is a constant. Backed "
                "by `libphonenumber`; offline and deterministic."
            ),
            description_md=(
                "# `is_valid_phone` (with region)\n\n"
                "Validate a phone number, parsing it in an explicit region.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.is_valid_phone('07911 123456', 'GB');  -- true\n"
                "```\n\n"
                "## Notes\n\n"
                "- `region` is an ISO-3166 alpha-2 code and must be a constant."
            ),
            keywords="phone, telephone, validate phone, region, country, is valid phone, libphonenumber",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.is_valid_phone('07911 123456', 'GB')",
                description="Validate a UK phone number",
            ),
        ]

    @classmethod
    def compute(
        cls,
        text: Annotated[pa.StringArray, Param(doc="Phone number to validate.")],
        region: Annotated[str, ConstParam("ISO-3166 alpha-2 region code, e.g. 'US', 'GB'.")],
    ) -> Annotated[pa.BooleanArray, Returns()]:
        """Map each input row to its output value."""
        return _map_bool(text, lambda x: validators.is_valid_phone(x, region))


# Each phone formatter / extractor below returns VARCHAR and comes in two arity
# overloads sharing a name: a default-region form and an explicit-``region`` form.
# (VGI scalars resolve overloads by arity; ``region`` cannot be a single-class
# default, so each is its own class -- see the module docstring.) The compute
# bodies are tiny ``_map_str`` calls over the matching ``validators`` function.


class FormatPhoneE164Function(ScalarFunction):
    """``format_phone_e164(text)`` -- E.164 form, region defaults to 'US'."""

    class Meta:
        """Function metadata."""

        name = "format_phone_e164"
        description = "Format a phone number as E.164, e.g. '+12024561111' (region defaults to 'US')"
        categories = ["conform", "phone"]
        tags = function_tags(
            title="Format Phone As E.164",
            description_llm=(
                "## `format_phone_e164(text)`\n\n"
                "Returns `VARCHAR`: the number in **E.164** form (`+<country><national>`, "
                "no spaces, e.g. `'+12024561111'`), or `NULL` when `text` is invalid or "
                "`NULL`. Parse region defaults to `'US'`.\n\n"
                "E.164 is the canonical, globally-unique storage form for phone numbers; "
                "normalize to it before storing, joining, or deduplicating. Use the "
                "`format_phone_e164(text, region)` overload for non-US input."
            ),
            description_md=(
                "# `format_phone_e164`\n\n"
                "Format a phone number into canonical E.164 (`+12024561111`).\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.format_phone_e164('202-456-1111');         -- '+12024561111'\n"
                "SELECT conform.format_phone_e164('07911 123456', 'GB');   -- region overload\n"
                "```\n\n"
                "## Notes\n\n"
                "- `NULL` / invalid input yields `NULL`. Default parse region `'US'`."
            ),
            keywords="phone, e164, e.164, format phone, canonical phone, normalize phone number",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.format_phone_e164('202-456-1111')",
                description="Format a US phone number as E.164",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Phone number.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, lambda x: validators.format_phone_e164(x, _DEFAULT_REGION))


class FormatPhoneE164RegionFunction(ScalarFunction):
    """``format_phone_e164(text, region)`` -- E.164 form in ``region``."""

    class Meta:
        """Function metadata."""

        name = "format_phone_e164"
        description = "Format a phone number as E.164 in a given region (NULL if invalid)"
        categories = ["conform", "phone"]
        tags = function_tags(
            title="Format Phone As E.164 In Region",
            description_llm=(
                "## `format_phone_e164(text, region)`\n\n"
                "Returns `VARCHAR`: the number in **E.164** form, parsing `text` with the "
                "explicit `region` (ISO-3166 alpha-2, e.g. `'GB'`), or `NULL` when invalid "
                "or `NULL`.\n\n"
                "Use this overload to canonicalize non-US numbers. `region` is a constant. "
                "E.164 is the recommended storage form."
            ),
            description_md=(
                "# `format_phone_e164` (with region)\n\n"
                "Format a phone number into E.164, parsing in an explicit region.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.format_phone_e164('07911 123456', 'GB');  -- '+447911123456'\n"
                "```\n\n"
                "## Notes\n\n"
                "- `region` is an ISO-3166 alpha-2 constant; `NULL`/invalid yields `NULL`."
            ),
            keywords="phone, e164, e.164, format phone, region, country, normalize phone number",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.format_phone_e164('07911 123456', 'GB')",
                description="Format a UK phone number as E.164",
            ),
        ]

    @classmethod
    def compute(
        cls,
        text: Annotated[pa.StringArray, Param(doc="Phone number.")],
        region: Annotated[str, ConstParam("ISO-3166 alpha-2 region code, e.g. 'US', 'GB'.")],
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, lambda x: validators.format_phone_e164(x, region))


class FormatPhoneNationalFunction(ScalarFunction):
    """``format_phone_national(text)`` -- national form, region defaults to 'US'."""

    class Meta:
        """Function metadata."""

        name = "format_phone_national"
        description = "Format a phone number in national form, e.g. '(202) 456-1111' (region 'US')"
        categories = ["conform", "phone"]
        tags = function_tags(
            title="Format Phone In National Form",
            description_llm=(
                "## `format_phone_national(text)`\n\n"
                "Returns `VARCHAR`: the number in **national** display form (e.g. "
                "`'(202) 456-1111'`), or `NULL` when invalid or `NULL`. Parse region "
                "defaults to `'US'`.\n\n"
                "National form is for human display **within** a country; for storage use "
                "`format_phone_e164` instead. Use `format_phone_national(text, region)` for "
                "non-US numbers."
            ),
            description_md=(
                "# `format_phone_national`\n\n"
                "Format a phone number in national display form.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.format_phone_national('2024561111');  -- '(202) 456-1111'\n"
                "```\n\n"
                "## Notes\n\n"
                "- For display, not storage. Default parse region `'US'`."
            ),
            keywords="phone, national format, format phone, display phone, pretty phone number",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.format_phone_national('2024561111')",
                description="Format a US phone number in national form",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Phone number.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, lambda x: validators.format_phone_national(x, _DEFAULT_REGION))


class FormatPhoneNationalRegionFunction(ScalarFunction):
    """``format_phone_national(text, region)`` -- national form in ``region``."""

    class Meta:
        """Function metadata."""

        name = "format_phone_national"
        description = "Format a phone number in national form in a given region (NULL if invalid)"
        categories = ["conform", "phone"]
        tags = function_tags(
            title="Format Phone In National Form By Region",
            description_llm=(
                "## `format_phone_national(text, region)`\n\n"
                "Returns `VARCHAR`: the number in **national** display form, parsing `text` "
                "with the explicit `region` (ISO-3166 alpha-2, e.g. `'GB'`), or `NULL` when "
                "invalid or `NULL`.\n\n"
                "Use this overload for non-US numbers. For storage prefer "
                "`format_phone_e164`. `region` is a constant."
            ),
            description_md=(
                "# `format_phone_national` (with region)\n\n"
                "Format a phone number in national form, parsing in an explicit region.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.format_phone_national('07911 123456', 'GB');  -- '07911 123456'\n"
                "```\n\n"
                "## Notes\n\n"
                "- `region` is an ISO-3166 alpha-2 constant; for display, not storage."
            ),
            keywords="phone, national format, region, country, format phone, display phone",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.format_phone_national('07911 123456', 'GB')",
                description="Format a UK phone number in national form",
            ),
        ]

    @classmethod
    def compute(
        cls,
        text: Annotated[pa.StringArray, Param(doc="Phone number.")],
        region: Annotated[str, ConstParam("ISO-3166 alpha-2 region code, e.g. 'US', 'GB'.")],
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, lambda x: validators.format_phone_national(x, region))


class FormatPhoneInternationalFunction(ScalarFunction):
    """``format_phone_international(text)`` -- international form, region 'US'."""

    class Meta:
        """Function metadata."""

        name = "format_phone_international"
        description = "Format a phone number in international form, e.g. '+1 202-456-1111' (region 'US')"
        categories = ["conform", "phone"]
        tags = function_tags(
            title="Format Phone In International Form",
            description_llm=(
                "## `format_phone_international(text)`\n\n"
                "Returns `VARCHAR`: the number in **international** display form (e.g. "
                "`'+1 202-456-1111'` -- country code plus spaced national groups), or "
                "`NULL` when invalid or `NULL`. Parse region defaults to `'US'`.\n\n"
                "International form is the human-readable, country-agnostic display variant; "
                "for canonical storage use `format_phone_e164`. Use "
                "`format_phone_international(text, region)` for non-US numbers."
            ),
            description_md=(
                "# `format_phone_international`\n\n"
                "Format a phone number in international display form.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.format_phone_international('202-456-1111');  -- '+1 202-456-1111'\n"
                "```\n\n"
                "## Notes\n\n"
                "- For display; use `format_phone_e164` for storage. Default region `'US'`."
            ),
            keywords="phone, international format, format phone, display phone, country code",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.format_phone_international('202-456-1111')",
                description="Format a US phone number in international form",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Phone number.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, lambda x: validators.format_phone_international(x, _DEFAULT_REGION))


class FormatPhoneInternationalRegionFunction(ScalarFunction):
    """``format_phone_international(text, region)`` -- international form in ``region``."""

    class Meta:
        """Function metadata."""

        name = "format_phone_international"
        description = "Format a phone number in international form in a given region (NULL if invalid)"
        categories = ["conform", "phone"]
        tags = function_tags(
            title="Format Phone In International Form By Region",
            description_llm=(
                "## `format_phone_international(text, region)`\n\n"
                "Returns `VARCHAR`: the number in **international** display form, parsing "
                "`text` with the explicit `region` (ISO-3166 alpha-2, e.g. `'GB'`), or "
                "`NULL` when invalid or `NULL`.\n\n"
                "Use this overload for non-US numbers. For storage prefer "
                "`format_phone_e164`. `region` is a constant."
            ),
            description_md=(
                "# `format_phone_international` (with region)\n\n"
                "Format a phone number in international form, parsing in an explicit region.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.format_phone_international('07911 123456', 'GB');\n"
                "-- '+44 7911 123456'\n"
                "```\n\n"
                "## Notes\n\n"
                "- `region` is an ISO-3166 alpha-2 constant; for display, not storage."
            ),
            keywords="phone, international format, region, country, format phone, country code",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.format_phone_international('07911 123456', 'GB')",
                description="Format a UK phone number in international form",
            ),
        ]

    @classmethod
    def compute(
        cls,
        text: Annotated[pa.StringArray, Param(doc="Phone number.")],
        region: Annotated[str, ConstParam("ISO-3166 alpha-2 region code, e.g. 'US', 'GB'.")],
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, lambda x: validators.format_phone_international(x, region))


class PhoneRegionFunction(ScalarFunction):
    """``phone_region(text)`` -- region the number belongs to, parsed as 'US'."""

    class Meta:
        """Function metadata."""

        name = "phone_region"
        description = "The ISO region a phone number belongs to (parse region defaults to 'US')"
        categories = ["conform", "phone"]
        tags = function_tags(
            title="Phone Number Region Code",
            description_llm=(
                "## `phone_region(text)`\n\n"
                "Returns `VARCHAR`: the ISO-3166 alpha-2 **region** a phone number belongs "
                "to (e.g. `'GB'` for `'+447911123456'`), or `NULL` when invalid or `NULL`. "
                "The *parse* region defaults to `'US'`, which matters mainly for "
                "national-format input.\n\n"
                "Use it to bucket numbers by country or to detect mismatches between a "
                "stated country and the actual number. Use `phone_region(text, region)` to "
                "parse national-format non-US input."
            ),
            description_md=(
                "# `phone_region`\n\n"
                "Determine the ISO region a phone number belongs to.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.phone_region('+447911123456');  -- 'GB'\n"
                "```\n\n"
                "## Notes\n\n"
                "- Parse region defaults to `'US'`; pass one for national-format input."
            ),
            keywords="phone, region, country, phone region, geocode phone, iso country",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.phone_region('+447911123456')",
                description="Region a number belongs to",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Phone number.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, lambda x: validators.phone_region(x, _DEFAULT_REGION))


class PhoneRegionRegionFunction(ScalarFunction):
    """``phone_region(text, region)`` -- region the number belongs to."""

    class Meta:
        """Function metadata."""

        name = "phone_region"
        description = "The ISO region a phone number belongs to, parsing in a given region (NULL if invalid)"
        categories = ["conform", "phone"]
        tags = function_tags(
            title="Phone Number Region Code By Parse Region",
            description_llm=(
                "## `phone_region(text, region)`\n\n"
                "Returns `VARCHAR`: the ISO-3166 alpha-2 region a phone number belongs to, "
                "parsing `text` with the explicit `region` (so national-format numbers "
                "resolve correctly), or `NULL` when invalid or `NULL`.\n\n"
                "Use this overload when input is in national format for a known non-US "
                "country. `region` is a constant."
            ),
            description_md=(
                "# `phone_region` (with region)\n\n"
                "Determine a number's region, parsing in an explicit region.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.phone_region('07911 123456', 'GB');  -- 'GB'\n"
                "```\n\n"
                "## Notes\n\n"
                "- `region` is an ISO-3166 alpha-2 constant used for parsing."
            ),
            keywords="phone, region, country, parse region, phone region, iso country",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.phone_region('07911 123456', 'GB')",
                description="Region a UK number belongs to",
            ),
        ]

    @classmethod
    def compute(
        cls,
        text: Annotated[pa.StringArray, Param(doc="Phone number.")],
        region: Annotated[str, ConstParam("ISO-3166 alpha-2 region code, e.g. 'US', 'GB'.")],
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, lambda x: validators.phone_region(x, region))


class PhoneTypeFunction(ScalarFunction):
    """``phone_type(text)`` -- line type, parsed as 'US'."""

    class Meta:
        """Function metadata."""

        name = "phone_type"
        description = "Line type of a phone number, e.g. 'mobile'/'fixed_line' (parse region 'US')"
        categories = ["conform", "phone"]
        tags = function_tags(
            title="Phone Number Line Type",
            description_llm=(
                "## `phone_type(text)`\n\n"
                "Returns `VARCHAR`: the **line type** of a phone number -- e.g. `'mobile'`, "
                "`'fixed_line'`, `'fixed_line_or_mobile'`, `'toll_free'`, `'voip'` -- or "
                "`NULL` when invalid or `NULL`. Parse region defaults to `'US'`.\n\n"
                "Use it to route by channel (e.g. only SMS to `'mobile'`), filter, or audit "
                "contact data. Use `phone_type(text, region)` for national-format non-US "
                "input."
            ),
            description_md=(
                "# `phone_type`\n\n"
                "Classify a phone number's line type (mobile / fixed line / ...).\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.phone_type('202-456-1111');  -- 'fixed_line_or_mobile'\n"
                "```\n\n"
                "## Notes\n\n"
                "- Parse region defaults to `'US'`. Values come from `libphonenumber`."
            ),
            keywords="phone, line type, mobile, fixed line, voip, toll free, phone type",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.phone_type('202-456-1111')",
                description="Line type of a US number",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Phone number.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, lambda x: validators.phone_type(x, _DEFAULT_REGION))


class PhoneTypeRegionFunction(ScalarFunction):
    """``phone_type(text, region)`` -- line type, parsed in ``region``."""

    class Meta:
        """Function metadata."""

        name = "phone_type"
        description = "Line type of a phone number, parsing in a given region (NULL if invalid)"
        categories = ["conform", "phone"]
        tags = function_tags(
            title="Phone Number Line Type By Region",
            description_llm=(
                "## `phone_type(text, region)`\n\n"
                "Returns `VARCHAR`: the **line type** of a phone number (`'mobile'`, "
                "`'fixed_line'`, ...), parsing `text` with the explicit `region`, or `NULL` "
                "when invalid or `NULL`.\n\n"
                "Use this overload for national-format non-US numbers. `region` is a "
                "constant."
            ),
            description_md=(
                "# `phone_type` (with region)\n\n"
                "Classify a number's line type, parsing in an explicit region.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.phone_type('07911 123456', 'GB');  -- 'mobile'\n"
                "```\n\n"
                "## Notes\n\n"
                "- `region` is an ISO-3166 alpha-2 constant used for parsing."
            ),
            keywords="phone, line type, mobile, fixed line, region, country, phone type",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.phone_type('07911 123456', 'GB')",
                description="Line type of a UK number",
            ),
        ]

    @classmethod
    def compute(
        cls,
        text: Annotated[pa.StringArray, Param(doc="Phone number.")],
        region: Annotated[str, ConstParam("ISO-3166 alpha-2 region code, e.g. 'US', 'GB'.")],
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, lambda x: validators.phone_type(x, region))


# ===========================================================================
# IBAN -- no extra argument.
# ===========================================================================


class IsValidIbanFunction(ScalarFunction):
    """``is_valid_iban(text)`` -- True if a structurally valid IBAN."""

    class Meta:
        """Function metadata."""

        name = "is_valid_iban"
        description = "True if text is a structurally valid IBAN (checksum included)"
        categories = ["conform", "iban"]
        tags = function_tags(
            title="Is Valid Bank IBAN",
            description_llm=(
                "## `is_valid_iban(text)`\n\n"
                "Returns `BOOLEAN`: `true` when `text` is a structurally valid "
                "International Bank Account Number -- correct per-country length and a "
                "passing **mod-97 checksum** -- `false` otherwise, `NULL` when `text` is "
                "`NULL`. Spaces are tolerated.\n\n"
                "Backed by `python-stdnum`; offline and deterministic. Use it to validate "
                "bank account fields before payment processing. Pair with `format_iban` for "
                "display and `iban_country` to extract the country."
            ),
            description_md=(
                "# `is_valid_iban`\n\n"
                "Validate an IBAN (length + mod-97 checksum).\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.is_valid_iban('GB82 WEST 1234 5698 7654 32');  -- true\n"
                "```\n\n"
                "## Notes\n\n"
                "- Spaces tolerated; `NULL` in yields `NULL` out."
            ),
            keywords="iban, bank account, validate iban, checksum, mod-97, banking",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.is_valid_iban('GB82 WEST 1234 5698 7654 32')",
                description="Validate an IBAN",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="IBAN to validate.")]
    ) -> Annotated[pa.BooleanArray, Returns()]:
        """Map each input row to its output value."""
        return _map_bool(text, validators.is_valid_iban)


class FormatIbanFunction(ScalarFunction):
    """``format_iban(text)`` -- IBAN grouped into 4s, or NULL if invalid."""

    class Meta:
        """Function metadata."""

        name = "format_iban"
        description = "IBAN grouped into space-separated blocks of four, or NULL if invalid"
        categories = ["conform", "iban"]
        tags = function_tags(
            title="Format IBAN For Display",
            description_llm=(
                "## `format_iban(text)`\n\n"
                "Returns `VARCHAR`: a valid IBAN grouped into space-separated blocks of "
                "four (the standard human-readable presentation, e.g. "
                "`'GB82 WEST 1234 5698 7654 32'`), or `NULL` when the IBAN is invalid or "
                "`NULL`.\n\n"
                "Because it returns `NULL` for invalid input, `format_iban` doubles as a "
                "validate-and-prettify step. For storage keep the compact form; use this "
                "only for display."
            ),
            description_md=(
                "# `format_iban`\n\n"
                "Pretty-print a valid IBAN in blocks of four.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.format_iban('GB82WEST12345698765432');\n"
                "-- 'GB82 WEST 1234 5698 7654 32'\n"
                "```\n\n"
                "## Notes\n\n"
                "- Returns `NULL` for invalid input (validate + format in one)."
            ),
            keywords="iban, format iban, pretty print iban, bank account, display iban, banking",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.format_iban('GB82WEST12345698765432')",
                description="Pretty-print an IBAN",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="IBAN to format.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, validators.format_iban)


class IbanCountryFunction(ScalarFunction):
    """``iban_country(text)`` -- the IBAN's country code, or NULL if invalid."""

    class Meta:
        """Function metadata."""

        name = "iban_country"
        description = "Two-letter country code of a valid IBAN, or NULL if invalid"
        categories = ["conform", "iban"]
        tags = function_tags(
            title="IBAN Country Code",
            description_llm=(
                "## `iban_country(text)`\n\n"
                "Returns `VARCHAR`: the two-letter ISO country code that prefixes a valid "
                "IBAN (e.g. `'GB'`), or `NULL` when the IBAN is invalid or `NULL`.\n\n"
                "Use it to group bank accounts by country, route SEPA vs non-SEPA, or audit "
                "that an account's country matches a customer's stated country. Validity is "
                "enforced -- a bad checksum yields `NULL`, not a spurious code."
            ),
            description_md=(
                "# `iban_country`\n\n"
                "Extract the country code from a valid IBAN.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.iban_country('GB82WEST12345698765432');  -- 'GB'\n"
                "```\n\n"
                "## Notes\n\n"
                "- Returns `NULL` for invalid IBANs (checksum enforced)."
            ),
            keywords="iban, country, country code, bank account, sepa, banking, iso country",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.iban_country('GB82WEST12345698765432')",
                description="Country code of an IBAN",
            ),
        ]

    @classmethod
    def compute(cls, text: Annotated[pa.StringArray, Param(doc="IBAN.")]) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, validators.iban_country)


# ===========================================================================
# VAT -- country overloads (default: EU validator over the prefixed number).
# ===========================================================================


class IsValidVatFunction(ScalarFunction):
    """``is_valid_vat(text)`` -- valid EU-prefixed VAT number."""

    class Meta:
        """Function metadata."""

        name = "is_valid_vat"
        description = "True if text is a valid EU VAT number (country-prefixed, e.g. 'DE136695976')"
        categories = ["conform", "vat"]
        tags = function_tags(
            title="Is Valid EU VAT Number",
            description_llm=(
                "## `is_valid_vat(text)`\n\n"
                "Returns `BOOLEAN`: `true` when `text` is a valid **country-prefixed** EU "
                "VAT number (e.g. `'DE136695976'`), `false` otherwise, `NULL` when `text` "
                "is `NULL`.\n\n"
                "Validation covers format and per-country check digits via "
                "`python-stdnum`'s `eu.vat`; it does **not** call VIES (offline, no "
                "network). Use the `is_valid_vat(text, country)` overload when you have the "
                "national (unprefixed) number plus a separate country code."
            ),
            description_md=(
                "# `is_valid_vat`\n\n"
                "Validate a country-prefixed EU VAT number.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.is_valid_vat('DE136695976');         -- true\n"
                "SELECT conform.is_valid_vat('136695976', 'DE');     -- country overload\n"
                "```\n\n"
                "## Notes\n\n"
                "- Offline structural/check-digit validation (no VIES lookup)."
            ),
            keywords="vat, eu vat, tax id, validate vat, vat number, value added tax",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.is_valid_vat('DE136695976')",
                description="Validate a country-prefixed EU VAT number",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="VAT number (country-prefixed).")]
    ) -> Annotated[pa.BooleanArray, Returns()]:
        """Map each input row to its output value."""
        return _map_bool(text, lambda x: validators.is_valid_vat(x, None))


class IsValidVatCountryFunction(ScalarFunction):
    """``is_valid_vat(text, country)`` -- valid national VAT for ``country``."""

    class Meta:
        """Function metadata."""

        name = "is_valid_vat"
        description = "True if text is a valid VAT number for a country (national, unprefixed form)"
        categories = ["conform", "vat"]
        tags = function_tags(
            title="Is Valid VAT Number For Country",
            description_llm=(
                "## `is_valid_vat(text, country)`\n\n"
                "Returns `BOOLEAN`: `true` when `text` is a valid **national** "
                "(unprefixed) VAT number for `country` (ISO-3166 alpha-2, e.g. `'DE'`), "
                "`false` otherwise, `NULL` when `text` is `NULL`.\n\n"
                "Dispatches to the country's `stdnum.<cc>.vat` module, falling back to the "
                "EU validator over the reconstructed prefixed number when no national module "
                "exists. Use this overload when country lives in its own column. `country` "
                "is a constant. Offline -- no VIES."
            ),
            description_md=(
                "# `is_valid_vat` (with country)\n\n"
                "Validate a national (unprefixed) VAT number for a country.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.is_valid_vat('136695976', 'DE');  -- true\n"
                "```\n\n"
                "## Notes\n\n"
                "- `country` is an ISO-3166 alpha-2 constant; offline validation."
            ),
            keywords="vat, eu vat, tax id, validate vat, country, national vat, value added tax",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.is_valid_vat('136695976', 'DE')",
                description="Validate a German VAT number (unprefixed)",
            ),
        ]

    @classmethod
    def compute(
        cls,
        text: Annotated[pa.StringArray, Param(doc="VAT number (national form).")],
        country: Annotated[str, ConstParam("ISO-3166 alpha-2 country code, e.g. 'DE', 'FR'.")],
    ) -> Annotated[pa.BooleanArray, Returns()]:
        """Map each input row to its output value."""
        return _map_bool(text, lambda x: validators.is_valid_vat(x, country))


class FormatVatFunction(ScalarFunction):
    """``format_vat(text)`` -- compact EU VAT number, or NULL if invalid."""

    class Meta:
        """Function metadata."""

        name = "format_vat"
        description = "Compact (stripped, upper-cased) EU VAT number, or NULL if invalid"
        categories = ["conform", "vat"]
        tags = function_tags(
            title="Format EU VAT Number",
            description_llm=(
                "## `format_vat(text)`\n\n"
                "Returns `VARCHAR`: the **compact** canonical form of a country-prefixed EU "
                "VAT number -- whitespace stripped, upper-cased (e.g. `'DE136695976'`) -- "
                "or `NULL` when the VAT number is invalid or `NULL`.\n\n"
                "Because invalid input yields `NULL`, this is a validate-and-normalize step "
                "in one; use it before storing or joining on VAT numbers so spacing/case "
                "variants collapse. Use `format_vat(text, country)` for national input."
            ),
            description_md=(
                "# `format_vat`\n\n"
                "Normalize a country-prefixed EU VAT number to compact form.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.format_vat('DE 136 695 976');  -- 'DE136695976'\n"
                "```\n\n"
                "## Notes\n\n"
                "- Returns `NULL` for invalid input (validate + normalize)."
            ),
            keywords="vat, eu vat, format vat, normalize vat, compact vat, tax id",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.format_vat('DE 136 695 976')",
                description="Compact an EU VAT number",
            ),
        ]

    @classmethod
    def compute(cls, text: Annotated[pa.StringArray, Param(doc="VAT number.")]) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, lambda x: validators.format_vat(x, None))


class FormatVatCountryFunction(ScalarFunction):
    """``format_vat(text, country)`` -- compact national VAT, or NULL."""

    class Meta:
        """Function metadata."""

        name = "format_vat"
        description = "Compact VAT number for a country (national form), or NULL if invalid"
        categories = ["conform", "vat"]
        tags = function_tags(
            title="Format VAT Number For Country",
            description_llm=(
                "## `format_vat(text, country)`\n\n"
                "Returns `VARCHAR`: the **compact** canonical form of a **national** "
                "(unprefixed) VAT number for `country` (ISO-3166 alpha-2), or `NULL` when "
                "invalid or `NULL`.\n\n"
                "Validates against the country's VAT rules and normalizes (strip/upper). "
                "Use this overload when country is a separate column. `country` is a "
                "constant."
            ),
            description_md=(
                "# `format_vat` (with country)\n\n"
                "Normalize a national (unprefixed) VAT number for a country.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.format_vat('136 695 976', 'DE');  -- '136695976'\n"
                "```\n\n"
                "## Notes\n\n"
                "- `country` is an ISO-3166 alpha-2 constant; `NULL` for invalid input."
            ),
            keywords="vat, format vat, normalize vat, country, national vat, tax id",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.format_vat('136 695 976', 'DE')",
                description="Compact a German VAT number",
            ),
        ]

    @classmethod
    def compute(
        cls,
        text: Annotated[pa.StringArray, Param(doc="VAT number (national form).")],
        country: Annotated[str, ConstParam("ISO-3166 alpha-2 country code, e.g. 'DE', 'FR'.")],
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, lambda x: validators.format_vat(x, country))


# ===========================================================================
# Credit card -- no extra argument.
# ===========================================================================


class IsValidCardFunction(ScalarFunction):
    """``is_valid_card(text)`` -- True if the digits pass the Luhn checksum."""

    class Meta:
        """Function metadata."""

        name = "is_valid_card"
        description = "True if the card number's digits pass the Luhn checksum"
        categories = ["conform", "card"]
        tags = function_tags(
            title="Is Valid Card Number",
            description_llm=(
                "## `is_valid_card(text)`\n\n"
                "Returns `BOOLEAN`: `true` when the card number's digits pass the **Luhn** "
                "checksum, `false` otherwise, `NULL` when `text` is `NULL`. Separators "
                "(spaces, dashes) are ignored.\n\n"
                "Luhn catches typos and many fabricated numbers but does **not** prove a "
                "card exists or is active. Note that validity is independent of brand: use "
                "`card_brand` to classify (a number can have a recognized brand yet fail "
                "Luhn, and vice versa)."
            ),
            description_md=(
                "# `is_valid_card`\n\n"
                "Check a card number against the Luhn checksum.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.is_valid_card('4111 1111 1111 1111');  -- true\n"
                "```\n\n"
                "## Notes\n\n"
                "- Luhn only -- not an authorization or existence check.\n"
                "- Independent of `card_brand`."
            ),
            keywords="credit card, card number, luhn, validate card, pan, payment, checksum",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.is_valid_card('4111 1111 1111 1111')",
                description="Validate a card number via Luhn",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Card number to validate.")]
    ) -> Annotated[pa.BooleanArray, Returns()]:
        """Map each input row to its output value."""
        return _map_bool(text, validators.is_valid_card)


class CardBrandFunction(ScalarFunction):
    """``card_brand(text)`` -- the card brand, or NULL if unrecognized."""

    class Meta:
        """Function metadata."""

        name = "card_brand"
        description = "Card brand (visa/mastercard/amex/discover/diners/jcb) by prefix+length, or NULL"
        categories = ["conform", "card"]
        tags = function_tags(
            title="Detect Card Brand",
            description_llm=(
                "## `card_brand(text)`\n\n"
                "Returns `VARCHAR`: the card **brand** -- one of `visa`, `mastercard`, "
                "`amex`, `discover`, `diners`, `jcb` -- inferred from the IIN/BIN prefix and "
                "length, or `NULL` when the number matches no known brand or is `NULL`. "
                "Separators are ignored.\n\n"
                "Classification is by prefix+length only and does **not** require a passing "
                "Luhn checksum (so malformed PANs can still be tagged); use `is_valid_card` "
                "for the checksum. See `card_brands()` for the full brand list."
            ),
            description_md=(
                "# `card_brand`\n\n"
                "Identify a card's brand from its prefix and length.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.card_brand('4111111111111111');  -- 'visa'\n"
                "```\n\n"
                "## Notes\n\n"
                "- Prefix+length only; independent of the Luhn check.\n"
                "- `card_brands()` lists every brand this can return."
            ),
            keywords="credit card, card brand, visa, mastercard, amex, discover, jcb, iin, bin, payment",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.card_brand('4111111111111111')",
                description="Detect the card brand",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Card number.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, validators.card_brand)


class MaskCardFunction(ScalarFunction):
    """``mask_card(text)`` -- keep the last 4 digits, mask the rest."""

    class Meta:
        """Function metadata."""

        name = "mask_card"
        description = "Mask all but the last four digits, e.g. '************1234' (NULL if <4 digits)"
        categories = ["conform", "card"]
        tags = function_tags(
            title="Mask Card Number",
            description_llm=(
                "## `mask_card(text)`\n\n"
                "Returns `VARCHAR`: the card number with every digit except the **last "
                "four** replaced by `*` (e.g. `'************1111'`), or `NULL` when the "
                "input has fewer than four digits or is `NULL`.\n\n"
                "Use it to safely display or log PANs without exposing the full number "
                "(PCI-friendly redaction). Separators are stripped before masking, so the "
                "output is a contiguous masked string."
            ),
            description_md=(
                "# `mask_card`\n\n"
                "Redact a card number, keeping only the last four digits.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.mask_card('4111-1111-1111-1111');  -- '************1111'\n"
                "```\n\n"
                "## Notes\n\n"
                "- Keeps the last 4 digits; `NULL` if fewer than 4 digits.\n"
                "- Separators are stripped before masking."
            ),
            keywords="credit card, mask card, redact, pan, last four, pci, payment, privacy",
            relative_path=_SCALARS_PATH,
            extra={
                "vgi.executable_examples": _EXECUTABLE_EXAMPLES_JSON,
            },
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.mask_card('4111-1111-1111-1111')",
                description="Mask a card number",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Card number to mask.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, validators.mask_card)


# ===========================================================================
# URL -- no extra argument.
# ===========================================================================


class IsValidUrlFunction(ScalarFunction):
    """``is_valid_url(text)`` -- True if an absolute URL with scheme + host."""

    class Meta:
        """Function metadata."""

        name = "is_valid_url"
        description = "True if text is an absolute URL with a scheme and host"
        categories = ["conform", "url"]
        tags = function_tags(
            title="Is Valid Web URL",
            description_llm=(
                "## `is_valid_url(text)`\n\n"
                "Returns `BOOLEAN`: `true` when `text` is an **absolute** URL with both a "
                "scheme and a host (e.g. `https://example.com/path`), `false` otherwise, "
                "`NULL` when `text` is `NULL`.\n\n"
                "This is a structural check -- it does not fetch the URL or verify the host "
                "resolves (offline). Relative URLs and bare hostnames return `false`. Pair "
                "with `normalize_url` / `url_host` to canonicalize or extract parts."
            ),
            description_md=(
                "# `is_valid_url`\n\n"
                "Check that a string is an absolute URL (scheme + host).\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.is_valid_url('https://example.com/path');  -- true\n"
                "```\n\n"
                "## Notes\n\n"
                "- Structural only -- no network fetch. Requires scheme and host."
            ),
            keywords="url, uri, link, validate url, is valid url, web address, http",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.is_valid_url('https://example.com/path')",
                description="Validate a URL",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="URL to validate.")]
    ) -> Annotated[pa.BooleanArray, Returns()]:
        """Map each input row to its output value."""
        return _map_bool(text, validators.is_valid_url)


class NormalizeUrlFunction(ScalarFunction):
    """``normalize_url(text)`` -- lower-case scheme/host, drop default port."""

    class Meta:
        """Function metadata."""

        name = "normalize_url"
        description = "Lower-case scheme + host and strip a default port, or NULL if invalid"
        categories = ["conform", "url"]
        tags = function_tags(
            title="Normalize Web URL",
            description_llm=(
                "## `normalize_url(text)`\n\n"
                "Returns `VARCHAR`: a canonicalized URL -- scheme and host lower-cased and a "
                "default port (`:80` for http, `:443` for https) stripped -- or `NULL` when "
                "the URL is invalid or `NULL`.\n\n"
                "Normalize before comparing, grouping, or deduplicating URLs so trivial "
                "variants (`HTTP://Example.com:80/Path` vs `http://example.com/Path`) "
                "collapse. Path/query case is preserved. Offline."
            ),
            description_md=(
                "# `normalize_url`\n\n"
                "Canonicalize a URL for comparison / deduplication.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.normalize_url('HTTP://Example.com:80/Path');\n"
                "-- 'http://example.com/Path'\n"
                "```\n\n"
                "## Notes\n\n"
                "- Lower-cases scheme+host, strips default port; keeps path/query case."
            ),
            keywords="url, uri, normalize url, canonical url, dedupe url, lowercase host, web address",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.normalize_url('HTTP://Example.com:80/Path')",
                description="Normalize a URL",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="URL to normalize.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, validators.normalize_url)


class UrlHostFunction(ScalarFunction):
    """``url_host(text)`` -- the lower-cased host, or NULL if invalid."""

    class Meta:
        """Function metadata."""

        name = "url_host"
        description = "Lower-cased host of a valid URL, or NULL if invalid"
        categories = ["conform", "url"]
        tags = function_tags(
            title="Extract URL Host",
            description_llm=(
                "## `url_host(text)`\n\n"
                "Returns `VARCHAR`: the lower-cased **host** (domain) of a valid URL (e.g. "
                "`'www.example.com'`), or `NULL` when the URL is invalid or `NULL`.\n\n"
                "Use it to group or filter by site/domain, build allow/deny lists, or join "
                "URL data on host. The port and userinfo are excluded; only the host is "
                "returned. Offline."
            ),
            description_md=(
                "# `url_host`\n\n"
                "Extract the (lower-cased) host from a URL.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.url_host('https://WWW.Example.com/a');  -- 'www.example.com'\n"
                "```\n\n"
                "## Notes\n\n"
                "- Host only (no port/userinfo); `NULL` for invalid URLs."
            ),
            keywords="url, uri, host, domain, url host, hostname, web address, group by domain",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.url_host('https://WWW.Example.com/a')",
                description="Extract the URL host",
            ),
        ]

    @classmethod
    def compute(cls, text: Annotated[pa.StringArray, Param(doc="URL.")]) -> Annotated[pa.StringArray, Returns()]:
        """Map each input row to its output value."""
        return _map_str(text, validators.url_host)


# ===========================================================================
# Postal -- requires a country; unknown country raises (surfaced as an error).
# ===========================================================================


class IsValidPostalCodeFunction(ScalarFunction):
    """``is_valid_postal_code(text, country)`` -- format check for ~10 countries."""

    class Meta:
        """Function metadata."""

        name = "is_valid_postal_code"
        description = (
            "True if text matches a country's postal-code format "
            "(modest coverage: US, CA, GB, DE, FR, NL, AU, JP, IN, BR). "
            "Unknown country raises an error."
        )
        categories = ["conform", "postal"]
        tags = function_tags(
            title="Is Valid Postal Code For Country",
            description_llm=(
                "## `is_valid_postal_code(text, country)`\n\n"
                "Returns `BOOLEAN`: `true` when `text` matches the postal-code **format** "
                "for `country` (ISO-3166 alpha-2), `false` when it does not, `NULL` when "
                "`text` is `NULL`.\n\n"
                "Coverage is intentionally modest -- a per-country regex table for US, CA, "
                "GB, DE, FR, NL, AU, JP, IN, BR. This is a **format** check, not "
                "deliverability validation. An **unknown** `country` raises an error "
                "(rather than silently returning `false`) so a country typo is not mistaken "
                "for an invalid code. `country` is a required constant."
            ),
            description_md=(
                "# `is_valid_postal_code`\n\n"
                "Format-check a postal code for a country.\n\n"
                "## Usage\n\n"
                "```sql\n"
                "SELECT conform.is_valid_postal_code('90210', 'US');     -- true\n"
                "SELECT conform.is_valid_postal_code('K1A 0B1', 'CA');   -- true\n"
                "```\n\n"
                "## Notes\n\n"
                "- Supported: US, CA, GB, DE, FR, NL, AU, JP, IN, BR.\n"
                "- Unknown `country` raises an error (caught typos, not silent `false`)."
            ),
            keywords="postal code, zip code, postcode, validate postal, country, address, format check",
            relative_path=_SCALARS_PATH,
        )
        examples = [
            FunctionExample(
                sql="SELECT conform.is_valid_postal_code('90210', 'US')",
                description="Validate a US ZIP code",
            ),
            FunctionExample(
                sql="SELECT conform.is_valid_postal_code('K1A 0B1', 'CA')",
                description="Validate a Canadian postal code",
            ),
        ]

    @classmethod
    def compute(
        cls,
        text: Annotated[pa.StringArray, Param(doc="Postal code to validate.")],
        country: Annotated[str, ConstParam("ISO-3166 alpha-2 country code, e.g. 'US', 'CA'.")],
    ) -> Annotated[pa.BooleanArray, Returns()]:
        """Map each input row to its output value."""
        # validators.is_valid_postal_code raises ValueError for unknown country;
        # raising here surfaces a clear DuckDB error (documented behaviour).
        return _map_bool(text, lambda x: validators.is_valid_postal_code(x, country))


SCALAR_FUNCTIONS: list[type] = [
    # email
    IsValidEmailFunction,
    NormalizeEmailFunction,
    EmailDomainFunction,
    # phone
    IsValidPhoneFunction,
    IsValidPhoneRegionFunction,
    FormatPhoneE164Function,
    FormatPhoneE164RegionFunction,
    FormatPhoneNationalFunction,
    FormatPhoneNationalRegionFunction,
    FormatPhoneInternationalFunction,
    FormatPhoneInternationalRegionFunction,
    PhoneRegionFunction,
    PhoneRegionRegionFunction,
    PhoneTypeFunction,
    PhoneTypeRegionFunction,
    # iban
    IsValidIbanFunction,
    FormatIbanFunction,
    IbanCountryFunction,
    # vat
    IsValidVatFunction,
    IsValidVatCountryFunction,
    FormatVatFunction,
    FormatVatCountryFunction,
    # card
    IsValidCardFunction,
    CardBrandFunction,
    MaskCardFunction,
    # url
    IsValidUrlFunction,
    NormalizeUrlFunction,
    UrlHostFunction,
    # postal
    IsValidPostalCodeFunction,
]
