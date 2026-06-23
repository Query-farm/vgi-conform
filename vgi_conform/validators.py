"""Pure validation + normalization logic for real-world structured data fields.

No Arrow or VGI dependency lives here -- just the underlying validation
libraries over plain ``str``. Keeping the logic in one importable,
side-effect-free module means it can be unit-tested directly and reused by the
Arrow-facing function adapters in the sibling modules.

Every function in this module takes a ``str`` (never ``None`` -- NULL handling
is the adapters' job) and is total: a ``is_valid_*`` predicate returns ``bool``
and never raises; a ``*format*`` / ``normalize_*`` / extractor returns ``str``
or ``None`` (``None`` meaning "invalid / not applicable") and never raises on
garbage input. The two exceptions are documented:

* :func:`is_valid_postal_code` raises :class:`ValueError` for an unknown country
  (its coverage is deliberately modest -- ~10 countries -- so an unsupported
  country is a caller error, not a silent ``false``).

Backends:

* **Phone** -- :mod:`phonenumbers` (Apache-2.0). Parse / validate / format
  (E.164, national, international), region, number type. A bad parse raises
  :class:`phonenumbers.NumberParseException`, caught here and treated as invalid.
* **IBAN / VAT / credit-card Luhn** -- :mod:`stdnum` (python-stdnum, LGPL-2.1):
  :mod:`stdnum.iban`, :mod:`stdnum.eu.vat`, :mod:`stdnum.luhn`.
* **Email** -- :mod:`email_validator` (CC0). Deliverability (DNS) checks are
  **disabled** so the worker stays offline and deterministic.
* **URL / postal** -- the standard library plus a small regex table; no network.
"""

from __future__ import annotations

import re
from urllib.parse import SplitResult, urlsplit, urlunsplit

import phonenumbers
from email_validator import EmailNotValidError, validate_email
from phonenumbers import NumberParseException, PhoneNumberFormat, PhoneNumberType
from stdnum import iban as _iban
from stdnum import luhn as _luhn
from stdnum.eu import vat as _eu_vat

_DEFAULT_REGION = "US"

# ---------------------------------------------------------------------------
# Email -- email-validator, deliverability (DNS) checks DISABLED (offline).
# ---------------------------------------------------------------------------


def _validated_email(text: str):  # type: ignore[no-untyped-def]
    """Return the email-validator result object, or ``None`` if invalid.

    ``check_deliverability=False`` keeps this purely syntactic / normalizing --
    no DNS, so it is hermetic and deterministic.
    """
    try:
        return validate_email(text, check_deliverability=False)
    except EmailNotValidError:
        return None


def is_valid_email(text: str) -> bool:
    """True if ``text`` is a syntactically valid email address (no DNS check)."""
    return _validated_email(text) is not None


def normalize_email(text: str) -> str | None:
    """The normalized form of ``text`` (lowercased domain, etc.), or ``None``."""
    result = _validated_email(text)
    return None if result is None else result.normalized


def email_domain(text: str) -> str | None:
    """The (normalized) domain part of ``text``, or ``None`` if invalid."""
    result = _validated_email(text)
    return None if result is None else result.domain


# ---------------------------------------------------------------------------
# Phone -- phonenumbers; region defaults to 'US'. Bad parses -> invalid/None.
# ---------------------------------------------------------------------------

_PHONE_TYPE_NAMES: dict[int, str] = {
    PhoneNumberType.FIXED_LINE: "fixed_line",
    PhoneNumberType.MOBILE: "mobile",
    PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed_line_or_mobile",
    PhoneNumberType.TOLL_FREE: "toll_free",
    PhoneNumberType.PREMIUM_RATE: "premium_rate",
    PhoneNumberType.SHARED_COST: "shared_cost",
    PhoneNumberType.VOIP: "voip",
    PhoneNumberType.PERSONAL_NUMBER: "personal_number",
    PhoneNumberType.PAGER: "pager",
    PhoneNumberType.UAN: "uan",
    PhoneNumberType.VOICEMAIL: "voicemail",
    PhoneNumberType.UNKNOWN: "unknown",
}


def _parse_phone(text: str, region: str) -> phonenumbers.PhoneNumber | None:
    """Parse and validate ``text`` in ``region``.

    Returns ``None`` if it cannot be parsed or is not a valid number. Never raises.
    """
    try:
        number = phonenumbers.parse(text, region.upper())
    except NumberParseException:
        return None
    if not phonenumbers.is_valid_number(number):
        return None
    return number


def is_valid_phone(text: str, region: str = _DEFAULT_REGION) -> bool:
    """True if ``text`` is a valid phone number when parsed as ``region``."""
    return _parse_phone(text, region) is not None


def _format_phone(text: str, region: str, fmt: int) -> str | None:
    number = _parse_phone(text, region)
    return None if number is None else phonenumbers.format_number(number, fmt)


def format_phone_e164(text: str, region: str = _DEFAULT_REGION) -> str | None:
    """E.164 form (e.g. ``+12024561111``), or ``None`` if invalid."""
    return _format_phone(text, region, PhoneNumberFormat.E164)


def format_phone_national(text: str, region: str = _DEFAULT_REGION) -> str | None:
    """National form (e.g. ``(202) 456-1111``), or ``None`` if invalid."""
    return _format_phone(text, region, PhoneNumberFormat.NATIONAL)


def format_phone_international(text: str, region: str = _DEFAULT_REGION) -> str | None:
    """International form (e.g. ``+1 202-456-1111``), or ``None`` if invalid."""
    return _format_phone(text, region, PhoneNumberFormat.INTERNATIONAL)


def phone_region(text: str, region: str = _DEFAULT_REGION) -> str | None:
    """ISO region code the number actually belongs to, or ``None`` if invalid."""
    number = _parse_phone(text, region)
    return None if number is None else phonenumbers.region_code_for_number(number)


def phone_type(text: str, region: str = _DEFAULT_REGION) -> str | None:
    """Line type (``mobile`` / ``fixed_line`` / ...), or ``None`` if invalid."""
    number = _parse_phone(text, region)
    if number is None:
        return None
    return _PHONE_TYPE_NAMES.get(phonenumbers.number_type(number), "unknown")


def supported_phone_regions() -> list[tuple[str, int]]:
    """Every ``(region, country_calling_code)`` pair phonenumbers supports.

    Sorted by region code. ``region`` is an ISO-3166 alpha-2 code usable as the
    ``region`` argument; ``country_code`` is its international dialling prefix.
    """
    out: list[tuple[str, int]] = []
    for region in sorted(phonenumbers.SUPPORTED_REGIONS):
        out.append((region, phonenumbers.country_code_for_region(region)))
    return out


# ---------------------------------------------------------------------------
# IBAN -- stdnum.iban.
# ---------------------------------------------------------------------------


def is_valid_iban(text: str) -> bool:
    """True if ``text`` is a structurally valid IBAN (checksum included)."""
    return bool(_iban.is_valid(text))


def format_iban(text: str) -> str | None:
    """IBAN grouped into space-separated blocks of four, or ``None`` if invalid."""
    if not _iban.is_valid(text):
        return None
    return _iban.format(text)


def iban_country(text: str) -> str | None:
    """The two-letter country code of a valid IBAN, or ``None`` if invalid."""
    if not _iban.is_valid(text):
        return None
    return _iban.compact(text)[:2]


# ---------------------------------------------------------------------------
# VAT -- stdnum.eu.vat for prefixed EU numbers; a country overload can dispatch
# to stdnum.<cc>.vat for an unprefixed national number.
# ---------------------------------------------------------------------------


def _country_vat_module(country: str):  # type: ignore[no-untyped-def]
    """Import ``stdnum.<cc>.vat`` for a country, or ``None`` if there isn't one."""
    cc = country.lower()
    try:
        module = __import__(f"stdnum.{cc}.vat", fromlist=["vat"])
    except ImportError:
        return None
    return module


def is_valid_vat(text: str, country: str | None = None) -> bool:
    """True if ``text`` is a valid VAT number.

    With no ``country`` the EU validator (:mod:`stdnum.eu.vat`) is used; it
    expects the country-prefixed form (e.g. ``DE136695976``). With a ``country``
    the national validator (:mod:`stdnum.<cc>.vat`) is used on the unprefixed
    number; an unknown country falls back to the EU validator.
    """
    if country is None:
        return bool(_eu_vat.is_valid(text))
    module = _country_vat_module(country)
    if module is None:
        return bool(_eu_vat.is_valid(text))
    return bool(module.is_valid(text))


def format_vat(text: str, country: str | None = None) -> str | None:
    """The compact (whitespace-stripped, upper-cased) VAT number, or ``None``.

    Returns ``None`` if the number is not valid for the chosen validator.
    """
    if not is_valid_vat(text, country):
        return None
    if country is None:
        return str(_eu_vat.compact(text))
    module = _country_vat_module(country)
    if module is None:
        return str(_eu_vat.compact(text))
    return str(module.compact(text))


# ---------------------------------------------------------------------------
# Credit card -- Luhn via stdnum; brand + masking implemented here.
# ---------------------------------------------------------------------------

_DIGITS_RE = re.compile(r"\D")


def _card_digits(text: str) -> str:
    """Strip everything but digits from a card-number string."""
    return _DIGITS_RE.sub("", text)


def is_valid_card(text: str) -> bool:
    """True if ``text``'s digits pass the Luhn checksum (and are 12-19 long)."""
    digits = _card_digits(text)
    if not 12 <= len(digits) <= 19:
        return False
    return bool(_luhn.is_valid(digits))


# Brand detection by IIN/BIN prefix + accepted lengths. Pure code, no library.
def card_brand(text: str) -> str | None:
    """The card brand for ``text``, or ``None`` if it matches none.

    Recognized brands: ``visa`` / ``mastercard`` / ``amex`` / ``discover`` /
    ``diners`` / ``jcb``. Detection is by prefix + length only; it does **not**
    require a passing Luhn checksum (use :func:`is_valid_card` for that).
    NULL/garbage -> ``None``.
    """
    d = _card_digits(text)
    n = len(d)
    if n < 12 or n > 19:
        return None

    def pref(*prefixes: str) -> bool:
        return any(d.startswith(p) for p in prefixes)

    # Visa: starts with 4, length 13/16/19.
    if d.startswith("4") and n in (13, 16, 19):
        return "visa"
    # Amex: 34/37, length 15.
    if pref("34", "37") and n == 15:
        return "amex"
    # Diners Club: 36, 38, 39, 300-305, length 14 (also 16 for some co-brands).
    two = d[:2]
    three = d[:3]
    if (two in {"36", "38", "39"} or ("300" <= three <= "305")) and n in (14, 16, 19):
        return "diners"
    # Mastercard: 51-55 or 2221-2720, length 16.
    four = d[:4]
    if n == 16 and (("51" <= two <= "55") or ("2221" <= four <= "2720")):
        return "mastercard"
    # Discover: 6011, 65, 644-649, 622126-622925, length 16/19.
    if n in (16, 19) and (
        d.startswith("6011") or two == "65" or ("644" <= three <= "649") or ("622126" <= d[:6] <= "622925")
    ):
        return "discover"
    # JCB: 3528-3589, length 16/19.
    if n in (16, 19) and ("3528" <= four <= "3589"):
        return "jcb"
    return None


def mask_card(text: str) -> str | None:
    """Mask all but the last four digits, e.g. ``************1234``.

    Returns ``None`` if there are fewer than four digits to keep. Operates on the
    digits only (separators are dropped); does not require a valid checksum.
    """
    d = _card_digits(text)
    if len(d) < 4:
        return None
    return "*" * (len(d) - 4) + d[-4:]


def card_brands() -> list[str]:
    """The brands :func:`card_brand` can return, alphabetically sorted."""
    return ["amex", "diners", "discover", "jcb", "mastercard", "visa"]


# ---------------------------------------------------------------------------
# URL -- stdlib urllib; normalize scheme/host casing, strip default port.
# ---------------------------------------------------------------------------

_DEFAULT_PORTS = {"http": 80, "https": 443, "ftp": 21, "ws": 80, "wss": 443}


def _split_url(text: str) -> SplitResult | None:
    """Parse and sanity-check a URL.

    Returns ``None`` unless it has an http(s)-style scheme *and* a host. Never raises.
    """
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    if not parts.scheme or not parts.hostname:
        return None
    # Require an absolute, network-style URL (scheme://host); reject e.g.
    # "mailto:" or bare "foo:bar" that urlsplit will still tokenize.
    if "//" not in text[: text.find(parts.path) if parts.path else len(text)]:
        return None
    return parts


def is_valid_url(text: str) -> bool:
    """True if ``text`` is an absolute URL with a scheme and host."""
    return _split_url(text) is not None


def normalize_url(text: str) -> str | None:
    """Lower-case the scheme + host and drop a default port, or ``None``.

    The path / query / fragment are preserved verbatim (case-sensitive). A
    default port for the scheme (``:80`` for http, ``:443`` for https, ...) is
    removed; any other explicit port is kept.
    """
    parts = _split_url(text)
    if parts is None:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    netloc = host
    if parts.port is not None and parts.port != _DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{parts.port}"
    userinfo = ""
    if parts.username is not None:
        userinfo = parts.username
        if parts.password is not None:
            userinfo += f":{parts.password}"
        netloc = f"{userinfo}@{netloc}"
    return urlunsplit((scheme, netloc, parts.path, parts.query, parts.fragment))


def url_host(text: str) -> str | None:
    """The lower-cased host of a valid URL, or ``None`` if invalid."""
    parts = _split_url(text)
    return None if parts is None else (parts.hostname or "").lower()


# ---------------------------------------------------------------------------
# Postal codes -- MODEST coverage: a per-country regex table (~10 countries).
# Unknown country -> ValueError (documented; callers/adapters surface it).
# ---------------------------------------------------------------------------

# Patterns are anchored, case-insensitive, and matched against the trimmed,
# upper-cased input. Coverage is intentionally limited to major countries; this
# is a convenience format check, not an authoritative deliverability validation.
_POSTAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "US": re.compile(r"^\d{5}(?:-\d{4})?$"),
    "CA": re.compile(r"^[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z] ?\d[ABCEGHJ-NPRSTV-Z]\d$"),
    "GB": re.compile(r"^(GIR 0AA|[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2})$"),
    "DE": re.compile(r"^\d{5}$"),
    "FR": re.compile(r"^\d{5}$"),
    "NL": re.compile(r"^\d{4} ?[A-Z]{2}$"),
    "AU": re.compile(r"^\d{4}$"),
    "JP": re.compile(r"^\d{3}-?\d{4}$"),
    "IN": re.compile(r"^\d{3} ?\d{3}$"),
    "BR": re.compile(r"^\d{5}-?\d{3}$"),
}


def supported_postal_countries() -> list[str]:
    """The country codes :func:`is_valid_postal_code` understands (sorted)."""
    return sorted(_POSTAL_PATTERNS)


def is_valid_postal_code(text: str, country: str) -> bool:
    """True if ``text`` matches ``country``'s postal-code format.

    Coverage is modest -- ~10 major countries (see
    :func:`supported_postal_countries`). An **unknown country** raises
    :class:`ValueError` rather than silently returning ``false``, so a typo in
    the country code is not mistaken for an invalid postal code.
    """
    cc = country.upper()
    pattern = _POSTAL_PATTERNS.get(cc)
    if pattern is None:
        raise ValueError(
            f"unsupported postal-code country {country!r}; supported: {', '.join(supported_postal_countries())}"
        )
    return pattern.match(text.strip().upper()) is not None
