"""Integration tests for the conform discovery table functions.

Drives ``supported_phone_regions``, ``card_brands``, and
``supported_postal_countries`` through the real bind -> init -> process
lifecycle in-process (no worker subprocess). The per-row functions are
*scalars* and are covered in ``test_scalars.py``.
"""

from __future__ import annotations

from vgi_conform import validators
from vgi_conform.tables import (
    CardBrandsFunction,
    SupportedPhoneRegionsFunction,
    SupportedPostalCountriesFunction,
)

from .harness import invoke_table_function


class TestSupportedPhoneRegions:
    def test_columns_and_nonempty(self) -> None:
        table = invoke_table_function(SupportedPhoneRegionsFunction)
        assert table.column_names == ["region", "country_code"]
        assert table.num_rows > 100

    def test_known_codes_present(self) -> None:
        table = invoke_table_function(SupportedPhoneRegionsFunction)
        mapping = dict(
            zip(
                table.column("region").to_pylist(),
                table.column("country_code").to_pylist(),
                strict=True,
            )
        )
        assert mapping["US"] == 1
        assert mapping["GB"] == 44

    def test_sorted_by_region(self) -> None:
        table = invoke_table_function(SupportedPhoneRegionsFunction)
        regions = table.column("region").to_pylist()
        assert regions == sorted(regions)


class TestCardBrands:
    def test_exact_set(self) -> None:
        table = invoke_table_function(CardBrandsFunction)
        assert table.column_names == ["brand"]
        assert table.column("brand").to_pylist() == [
            "amex",
            "diners",
            "discover",
            "jcb",
            "mastercard",
            "visa",
        ]


class TestSupportedPostalCountries:
    def test_columns_and_matches_validators(self) -> None:
        table = invoke_table_function(SupportedPostalCountriesFunction)
        assert table.column_names == ["country"]
        assert table.column("country").to_pylist() == validators.supported_postal_countries()

    def test_known_countries_present_and_sorted(self) -> None:
        table = invoke_table_function(SupportedPostalCountriesFunction)
        countries = table.column("country").to_pylist()
        assert countries == sorted(countries)
        assert {"US", "CA", "GB"} <= set(countries)
