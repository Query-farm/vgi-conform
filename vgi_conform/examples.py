"""Composed example queries that combine several conform objects in one query.

Most examples in this worker demonstrate one function in isolation. The queries
here show how the pieces fit together in the cleanup jobs people actually run --
an extractor feeding a filter, a normalizer feeding an aggregate, a discovery
table joined to per-row results. Each SQL string is defined once here and
referenced from the schema-level ``vgi.example_queries`` list, from the
``Meta.examples`` / ``vgi.example_queries`` of the object that drives the query,
and (when offline + deterministic, which all of these are) from
``vgi.executable_examples``. ``test/sql/composed.test`` pins their output.
"""

from __future__ import annotations

from vgi.metadata import FunctionExample

# Signups per email domain: invalid addresses dropped, then addresses that differ
# only in domain case collapse under normalize_email (local-part case is kept).
EMAIL_DOMAIN_DEDUP_SQL = (
    "WITH signups(email) AS (VALUES ('Ann@Example.COM'), ('Ann@example.com'), "
    "('bob@Mail.Example.org'), ('carol@example.com'), ('not-an-email')) "
    "SELECT conform.main.email_domain(email) AS domain, count(*) AS signup_rows, "
    "count(DISTINCT conform.main.normalize_email(email)) AS unique_addresses "
    "FROM signups WHERE conform.main.is_valid_email(email) "
    "GROUP BY domain ORDER BY domain"
)
EMAIL_DOMAIN_DEDUP_DESCRIPTION = (
    "Count sign-ups per email domain after dropping invalid addresses, collapsing addresses "
    "that differ only in domain case into one unique address."
)

# Contacts whose phone number belongs to a different region than the country
# they claim (and canonical E.164 + line type for review).
PHONE_COUNTRY_MISMATCH_SQL = (
    "WITH contacts(name, country, phone) AS (VALUES "
    "('Ada', 'GB', '+44 7400 123456'), ('Bea', 'US', '+49 30 901820'), "
    "('Cal', 'FR', '+33 6 12 34 56 78'), ('Dov', 'US', '(202) 456-1111'), ('Eli', 'US', '12345')) "
    "SELECT name, country, conform.main.phone_region(phone) AS phone_region, "
    "conform.main.format_phone_e164(phone) AS e164, conform.main.phone_type(phone) AS line_type "
    "FROM contacts WHERE conform.main.is_valid_phone(phone) "
    "AND conform.main.phone_region(phone) <> country ORDER BY name"
)
PHONE_COUNTRY_MISMATCH_DESCRIPTION = (
    "Find contacts whose (valid) phone number belongs to a different country than the one on "
    "their record, showing the number's real region, E.164 form and line type."
)

# Every recognized brand with how many payment PANs carry it and how many of
# those pass Luhn -- brands with no cards still appear with zero counts.
CARD_BRAND_COVERAGE_SQL = (
    "WITH payments(pan) AS (VALUES ('4111 1111 1111 1111'), ('4111 1111 1111 1112'), "
    "('5555 5555 5555 4444'), ('3782 822463 10005'), ('6011111111111117'), ('9999 0000')) "
    "SELECT b.brand, count(p.pan) AS cards, "
    "count(p.pan) FILTER (WHERE conform.main.is_valid_card(p.pan)) AS luhn_valid "
    "FROM conform.main.card_brands AS b "
    "LEFT JOIN payments AS p ON conform.main.card_brand(p.pan) = b.brand "
    "GROUP BY b.brand ORDER BY b.brand"
)
CARD_BRAND_COVERAGE_DESCRIPTION = (
    "For every recognized card brand, count the payment card numbers of that brand and how many "
    "pass the Luhn check; brands with no cards show zero and unrecognized numbers are left out."
)

# Supplier bank-detail audit: IBAN validity, pretty-printed IBAN, and whether
# the IBAN's country matches the country prefix of the normalized VAT number.
SUPPLIER_IBAN_VAT_SQL = (
    "WITH suppliers(name, iban, vat) AS (VALUES "
    "('Alpen GmbH', 'DE89 3704 0044 0532 0130 00', 'DE 136 695 976'), "
    "('Thames Ltd', 'GB82WEST12345698765432', 'DE136695976'), "
    "('Seine SA', 'FR1420041010050500013M02606', 'FR40303265045'), "
    "('Typo BV', 'NL00ABNA0417164300', 'NL004495445B01')) "
    "SELECT name, conform.main.is_valid_iban(iban) AS iban_ok, conform.main.format_iban(iban) AS iban, "
    "conform.main.iban_country(iban) AS iban_country, conform.main.format_vat(vat) AS vat, "
    "conform.main.iban_country(iban) = left(conform.main.format_vat(vat), 2) AS countries_match "
    "FROM suppliers ORDER BY name"
)
SUPPLIER_IBAN_VAT_DESCRIPTION = (
    "Audit supplier bank details: validate and pretty-print each IBAN, normalize the VAT number, "
    "and flag whether the IBAN's country matches the VAT number's country (NULL when the IBAN is "
    "invalid)."
)

EMAIL_DOMAIN_DEDUP = FunctionExample(sql=EMAIL_DOMAIN_DEDUP_SQL, description=EMAIL_DOMAIN_DEDUP_DESCRIPTION)
PHONE_COUNTRY_MISMATCH = FunctionExample(sql=PHONE_COUNTRY_MISMATCH_SQL, description=PHONE_COUNTRY_MISMATCH_DESCRIPTION)
CARD_BRAND_COVERAGE = FunctionExample(sql=CARD_BRAND_COVERAGE_SQL, description=CARD_BRAND_COVERAGE_DESCRIPTION)
SUPPLIER_IBAN_VAT = FunctionExample(sql=SUPPLIER_IBAN_VAT_SQL, description=SUPPLIER_IBAN_VAT_DESCRIPTION)

COMPOSED_EXAMPLES: list[FunctionExample] = [
    EMAIL_DOMAIN_DEDUP,
    PHONE_COUNTRY_MISMATCH,
    SUPPLIER_IBAN_VAT,
    CARD_BRAND_COVERAGE,
]


def as_query(example: FunctionExample) -> dict[str, str]:
    """Render a ``FunctionExample`` as a ``{description, sql}`` example-query entry.

    Args:
        example: The example to render.

    Returns:
        The ``{"description": ..., "sql": ...}`` dict used by ``vgi.example_queries``
        and ``vgi.executable_examples``.
    """
    return {"description": example.description, "sql": example.sql}
