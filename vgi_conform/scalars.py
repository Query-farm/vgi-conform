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

from collections.abc import Callable
from typing import Annotated

import pyarrow as pa
from vgi.arguments import ConstParam, Param, Returns
from vgi.metadata import FunctionExample
from vgi.scalar_function import ScalarFunction

from . import validators

_DEFAULT_REGION = "US"


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
        name = "is_valid_email"
        description = "True if text is a syntactically valid email address (no DNS lookup)"
        categories = ["conform", "email"]
        examples = [
            FunctionExample(sql="SELECT conform.is_valid_email('a@b.com')", description="Valid email"),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="Email address to validate.")]
    ) -> Annotated[pa.BooleanArray, Returns()]:
        return _map_bool(text, validators.is_valid_email)


class NormalizeEmailFunction(ScalarFunction):
    """``normalize_email(text)`` -- normalized email, or NULL if invalid."""

    class Meta:
        name = "normalize_email"
        description = "Normalized email address (lower-cased domain, etc.), or NULL if invalid"
        categories = ["conform", "email"]
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
        return _map_str(text, validators.normalize_email)


class EmailDomainFunction(ScalarFunction):
    """``email_domain(text)`` -- the domain part, or NULL if invalid."""

    class Meta:
        name = "email_domain"
        description = "The (normalized) domain part of an email address, or NULL if invalid"
        categories = ["conform", "email"]
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
        return _map_str(text, validators.email_domain)


# ===========================================================================
# Phone -- region overloads (default 'US').
# ===========================================================================


class IsValidPhoneFunction(ScalarFunction):
    """``is_valid_phone(text)`` -- valid phone parsed as US."""

    class Meta:
        name = "is_valid_phone"
        description = "True if text is a valid phone number (region defaults to 'US')"
        categories = ["conform", "phone"]
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
        return _map_bool(text, lambda x: validators.is_valid_phone(x, _DEFAULT_REGION))


class IsValidPhoneRegionFunction(ScalarFunction):
    """``is_valid_phone(text, region)`` -- valid phone parsed as ``region``."""

    class Meta:
        name = "is_valid_phone"
        description = "True if text is a valid phone number in a given region"
        categories = ["conform", "phone"]
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
        return _map_bool(text, lambda x: validators.is_valid_phone(x, region))


# Each phone formatter / extractor below returns VARCHAR and comes in two arity
# overloads sharing a name: a default-region form and an explicit-``region`` form.
# (VGI scalars resolve overloads by arity; ``region`` cannot be a single-class
# default, so each is its own class -- see the module docstring.) The compute
# bodies are tiny ``_map_str`` calls over the matching ``validators`` function.


class FormatPhoneE164Function(ScalarFunction):
    """``format_phone_e164(text)`` -- E.164 form, region defaults to 'US'."""

    class Meta:
        name = "format_phone_e164"
        description = "Format a phone number as E.164, e.g. '+12024561111' (region defaults to 'US')"
        categories = ["conform", "phone"]
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
        return _map_str(text, lambda x: validators.format_phone_e164(x, _DEFAULT_REGION))


class FormatPhoneE164RegionFunction(ScalarFunction):
    """``format_phone_e164(text, region)`` -- E.164 form in ``region``."""

    class Meta:
        name = "format_phone_e164"
        description = "Format a phone number as E.164 in a given region (NULL if invalid)"
        categories = ["conform", "phone"]
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
        return _map_str(text, lambda x: validators.format_phone_e164(x, region))


class FormatPhoneNationalFunction(ScalarFunction):
    """``format_phone_national(text)`` -- national form, region defaults to 'US'."""

    class Meta:
        name = "format_phone_national"
        description = "Format a phone number in national form, e.g. '(202) 456-1111' (region 'US')"
        categories = ["conform", "phone"]
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
        return _map_str(text, lambda x: validators.format_phone_national(x, _DEFAULT_REGION))


class FormatPhoneNationalRegionFunction(ScalarFunction):
    """``format_phone_national(text, region)`` -- national form in ``region``."""

    class Meta:
        name = "format_phone_national"
        description = "Format a phone number in national form in a given region (NULL if invalid)"
        categories = ["conform", "phone"]
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
        return _map_str(text, lambda x: validators.format_phone_national(x, region))


class FormatPhoneInternationalFunction(ScalarFunction):
    """``format_phone_international(text)`` -- international form, region 'US'."""

    class Meta:
        name = "format_phone_international"
        description = "Format a phone number in international form, e.g. '+1 202-456-1111' (region 'US')"
        categories = ["conform", "phone"]
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
        return _map_str(text, lambda x: validators.format_phone_international(x, _DEFAULT_REGION))


class FormatPhoneInternationalRegionFunction(ScalarFunction):
    """``format_phone_international(text, region)`` -- international form in ``region``."""

    class Meta:
        name = "format_phone_international"
        description = "Format a phone number in international form in a given region (NULL if invalid)"
        categories = ["conform", "phone"]
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
        return _map_str(text, lambda x: validators.format_phone_international(x, region))


class PhoneRegionFunction(ScalarFunction):
    """``phone_region(text)`` -- region the number belongs to, parsed as 'US'."""

    class Meta:
        name = "phone_region"
        description = "The ISO region a phone number belongs to (parse region defaults to 'US')"
        categories = ["conform", "phone"]
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
        return _map_str(text, lambda x: validators.phone_region(x, _DEFAULT_REGION))


class PhoneRegionRegionFunction(ScalarFunction):
    """``phone_region(text, region)`` -- region the number belongs to."""

    class Meta:
        name = "phone_region"
        description = "The ISO region a phone number belongs to, parsing in a given region (NULL if invalid)"
        categories = ["conform", "phone"]
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
        return _map_str(text, lambda x: validators.phone_region(x, region))


class PhoneTypeFunction(ScalarFunction):
    """``phone_type(text)`` -- line type, parsed as 'US'."""

    class Meta:
        name = "phone_type"
        description = "Line type of a phone number, e.g. 'mobile'/'fixed_line' (parse region 'US')"
        categories = ["conform", "phone"]
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
        return _map_str(text, lambda x: validators.phone_type(x, _DEFAULT_REGION))


class PhoneTypeRegionFunction(ScalarFunction):
    """``phone_type(text, region)`` -- line type, parsed in ``region``."""

    class Meta:
        name = "phone_type"
        description = "Line type of a phone number, parsing in a given region (NULL if invalid)"
        categories = ["conform", "phone"]
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
        return _map_str(text, lambda x: validators.phone_type(x, region))


# ===========================================================================
# IBAN -- no extra argument.
# ===========================================================================


class IsValidIbanFunction(ScalarFunction):
    """``is_valid_iban(text)`` -- True if a structurally valid IBAN."""

    class Meta:
        name = "is_valid_iban"
        description = "True if text is a structurally valid IBAN (checksum included)"
        categories = ["conform", "iban"]
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
        return _map_bool(text, validators.is_valid_iban)


class FormatIbanFunction(ScalarFunction):
    """``format_iban(text)`` -- IBAN grouped into 4s, or NULL if invalid."""

    class Meta:
        name = "format_iban"
        description = "IBAN grouped into space-separated blocks of four, or NULL if invalid"
        categories = ["conform", "iban"]
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
        return _map_str(text, validators.format_iban)


class IbanCountryFunction(ScalarFunction):
    """``iban_country(text)`` -- the IBAN's country code, or NULL if invalid."""

    class Meta:
        name = "iban_country"
        description = "Two-letter country code of a valid IBAN, or NULL if invalid"
        categories = ["conform", "iban"]
        examples = [
            FunctionExample(
                sql="SELECT conform.iban_country('GB82WEST12345698765432')",
                description="Country code of an IBAN",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="IBAN.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        return _map_str(text, validators.iban_country)


# ===========================================================================
# VAT -- country overloads (default: EU validator over the prefixed number).
# ===========================================================================


class IsValidVatFunction(ScalarFunction):
    """``is_valid_vat(text)`` -- valid EU-prefixed VAT number."""

    class Meta:
        name = "is_valid_vat"
        description = "True if text is a valid EU VAT number (country-prefixed, e.g. 'DE136695976')"
        categories = ["conform", "vat"]
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
        return _map_bool(text, lambda x: validators.is_valid_vat(x, None))


class IsValidVatCountryFunction(ScalarFunction):
    """``is_valid_vat(text, country)`` -- valid national VAT for ``country``."""

    class Meta:
        name = "is_valid_vat"
        description = "True if text is a valid VAT number for a country (national, unprefixed form)"
        categories = ["conform", "vat"]
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
        return _map_bool(text, lambda x: validators.is_valid_vat(x, country))


class FormatVatFunction(ScalarFunction):
    """``format_vat(text)`` -- compact EU VAT number, or NULL if invalid."""

    class Meta:
        name = "format_vat"
        description = "Compact (stripped, upper-cased) EU VAT number, or NULL if invalid"
        categories = ["conform", "vat"]
        examples = [
            FunctionExample(
                sql="SELECT conform.format_vat('DE 136 695 976')",
                description="Compact an EU VAT number",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="VAT number.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        return _map_str(text, lambda x: validators.format_vat(x, None))


class FormatVatCountryFunction(ScalarFunction):
    """``format_vat(text, country)`` -- compact national VAT, or NULL."""

    class Meta:
        name = "format_vat"
        description = "Compact VAT number for a country (national form), or NULL if invalid"
        categories = ["conform", "vat"]
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
        return _map_str(text, lambda x: validators.format_vat(x, country))


# ===========================================================================
# Credit card -- no extra argument.
# ===========================================================================


class IsValidCardFunction(ScalarFunction):
    """``is_valid_card(text)`` -- True if the digits pass the Luhn checksum."""

    class Meta:
        name = "is_valid_card"
        description = "True if the card number's digits pass the Luhn checksum"
        categories = ["conform", "card"]
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
        return _map_bool(text, validators.is_valid_card)


class CardBrandFunction(ScalarFunction):
    """``card_brand(text)`` -- the card brand, or NULL if unrecognized."""

    class Meta:
        name = "card_brand"
        description = "Card brand (visa/mastercard/amex/discover/diners/jcb) by prefix+length, or NULL"
        categories = ["conform", "card"]
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
        return _map_str(text, validators.card_brand)


class MaskCardFunction(ScalarFunction):
    """``mask_card(text)`` -- keep the last 4 digits, mask the rest."""

    class Meta:
        name = "mask_card"
        description = "Mask all but the last four digits, e.g. '************1234' (NULL if <4 digits)"
        categories = ["conform", "card"]
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
        return _map_str(text, validators.mask_card)


# ===========================================================================
# URL -- no extra argument.
# ===========================================================================


class IsValidUrlFunction(ScalarFunction):
    """``is_valid_url(text)`` -- True if an absolute URL with scheme + host."""

    class Meta:
        name = "is_valid_url"
        description = "True if text is an absolute URL with a scheme and host"
        categories = ["conform", "url"]
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
        return _map_bool(text, validators.is_valid_url)


class NormalizeUrlFunction(ScalarFunction):
    """``normalize_url(text)`` -- lower-case scheme/host, drop default port."""

    class Meta:
        name = "normalize_url"
        description = "Lower-case scheme + host and strip a default port, or NULL if invalid"
        categories = ["conform", "url"]
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
        return _map_str(text, validators.normalize_url)


class UrlHostFunction(ScalarFunction):
    """``url_host(text)`` -- the lower-cased host, or NULL if invalid."""

    class Meta:
        name = "url_host"
        description = "Lower-cased host of a valid URL, or NULL if invalid"
        categories = ["conform", "url"]
        examples = [
            FunctionExample(
                sql="SELECT conform.url_host('https://WWW.Example.com/a')",
                description="Extract the URL host",
            ),
        ]

    @classmethod
    def compute(
        cls, text: Annotated[pa.StringArray, Param(doc="URL.")]
    ) -> Annotated[pa.StringArray, Returns()]:
        return _map_str(text, validators.url_host)


# ===========================================================================
# Postal -- requires a country; unknown country raises (surfaced as an error).
# ===========================================================================


class IsValidPostalCodeFunction(ScalarFunction):
    """``is_valid_postal_code(text, country)`` -- format check for ~10 countries."""

    class Meta:
        name = "is_valid_postal_code"
        description = (
            "True if text matches a country's postal-code format "
            "(modest coverage: US, CA, GB, DE, FR, NL, AU, JP, IN, BR). "
            "Unknown country raises an error."
        )
        categories = ["conform", "postal"]
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
