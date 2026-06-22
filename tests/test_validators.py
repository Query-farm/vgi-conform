"""Unit tests for the pure validation/normalization logic in ``validators``.

Strong error / edge coverage: empty and garbage inputs, bad checksums,
wrong-region phones, non-EU VAT, Luhn failures, malformed URLs, and the
unknown-country postal error.
"""

from __future__ import annotations

import pytest

from vgi_conform import validators as v


class TestEmail:
    def test_valid(self) -> None:
        assert v.is_valid_email("a@b.com") is True

    def test_normalize_lowercases_domain(self) -> None:
        assert v.normalize_email("Test@Example.COM") == "Test@example.com"

    def test_domain(self) -> None:
        assert v.email_domain("a@Example.com") == "example.com"

    def test_invalid_returns_false_and_none(self) -> None:
        assert v.is_valid_email("not-an-email") is False
        assert v.normalize_email("not-an-email") is None
        assert v.email_domain("not-an-email") is None

    def test_empty_string_invalid(self) -> None:
        assert v.is_valid_email("") is False
        assert v.normalize_email("") is None

    def test_missing_domain_invalid(self) -> None:
        assert v.is_valid_email("a@") is False

    def test_missing_local_invalid(self) -> None:
        assert v.is_valid_email("@b.com") is False

    def test_garbage_invalid(self) -> None:
        assert v.is_valid_email("a b@c d.com") is False


class TestPhone:
    def test_valid_us_default(self) -> None:
        assert v.is_valid_phone("202-456-1111") is True

    def test_e164(self) -> None:
        assert v.format_phone_e164("202-456-1111") == "+12024561111"

    def test_national(self) -> None:
        assert v.format_phone_national("202-456-1111") == "(202) 456-1111"

    def test_international(self) -> None:
        assert v.format_phone_international("202-456-1111") == "+1 202-456-1111"

    def test_region_overload(self) -> None:
        assert v.is_valid_phone("07911 123456", "GB") is True
        assert v.format_phone_e164("07911 123456", "GB") == "+447911123456"

    def test_type_mobile_vs_fixed(self) -> None:
        assert v.phone_type("07911 123456", "GB") == "mobile"
        # US toll-free.
        assert v.phone_type("800-555-0199") in {"toll_free", "unknown"}

    def test_wrong_region_invalid(self) -> None:
        # A UK mobile parsed as US is not a valid US number.
        assert v.is_valid_phone("07911 123456", "US") is False
        assert v.format_phone_e164("07911 123456", "US") is None

    def test_garbage_never_raises(self) -> None:
        assert v.is_valid_phone("not a phone") is False
        assert v.format_phone_e164("not a phone") is None
        assert v.phone_region("xyz") is None
        assert v.phone_type("xyz") is None

    def test_empty_string(self) -> None:
        assert v.is_valid_phone("") is False
        assert v.format_phone_national("") is None

    def test_too_short(self) -> None:
        assert v.is_valid_phone("123") is False

    def test_region_of_number(self) -> None:
        assert v.phone_region("+12024561111") == "US"

    def test_supported_regions_nonempty(self) -> None:
        regions = v.supported_phone_regions()
        assert len(regions) > 100
        codes = dict(regions)
        assert codes["US"] == 1
        assert codes["GB"] == 44


class TestIban:
    def test_valid(self) -> None:
        assert v.is_valid_iban("GB82 WEST 1234 5698 7654 32") is True

    def test_format_groups_of_four(self) -> None:
        assert v.format_iban("GB82WEST12345698765432") == "GB82 WEST 1234 5698 7654 32"

    def test_country(self) -> None:
        assert v.iban_country("GB82WEST12345698765432") == "GB"

    def test_bad_checksum_invalid(self) -> None:
        # Flip the check digits.
        assert v.is_valid_iban("GB00WEST12345698765432") is False
        assert v.format_iban("GB00WEST12345698765432") is None
        assert v.iban_country("GB00WEST12345698765432") is None

    def test_garbage_invalid(self) -> None:
        assert v.is_valid_iban("not an iban") is False
        assert v.format_iban("") is None


class TestVat:
    def test_eu_prefixed_valid(self) -> None:
        assert v.is_valid_vat("DE136695976") is True

    def test_eu_prefixed_format(self) -> None:
        assert v.format_vat("DE 136 695 976") == "DE136695976"

    def test_country_overload_unprefixed(self) -> None:
        assert v.is_valid_vat("136695976", "DE") is True
        assert v.format_vat("136 695 976", "DE") == "136695976"

    def test_non_eu_invalid(self) -> None:
        # A US-style number is not a valid EU VAT.
        assert v.is_valid_vat("US123456789") is False
        assert v.format_vat("US123456789") is None

    def test_bad_eu_number_invalid(self) -> None:
        assert v.is_valid_vat("DE000000000") is False

    def test_unknown_country_falls_back_to_eu(self) -> None:
        # No stdnum.zz.vat module -> EU validator over the raw text -> invalid.
        assert v.is_valid_vat("136695976", "ZZ") is False

    def test_empty_invalid(self) -> None:
        assert v.is_valid_vat("") is False


class TestCard:
    def test_luhn_valid(self) -> None:
        assert v.is_valid_card("4111 1111 1111 1111") is True

    def test_luhn_failure(self) -> None:
        assert v.is_valid_card("4111 1111 1111 1112") is False

    def test_too_short_invalid(self) -> None:
        assert v.is_valid_card("4111") is False

    def test_brands(self) -> None:
        assert v.card_brand("4111111111111111") == "visa"
        assert v.card_brand("5555555555554444") == "mastercard"
        assert v.card_brand("2221000000000009") == "mastercard"
        assert v.card_brand("378282246310005") == "amex"
        assert v.card_brand("6011111111111117") == "discover"
        assert v.card_brand("36227206271667") == "diners"
        assert v.card_brand("3530111333300000") == "jcb"

    def test_brand_unknown(self) -> None:
        assert v.card_brand("1234567812345670") is None
        assert v.card_brand("") is None
        assert v.card_brand("not a card") is None

    def test_brand_does_not_require_luhn(self) -> None:
        # Right prefix + length but failing checksum still classifies as visa.
        assert v.card_brand("4111111111111112") == "visa"

    def test_mask(self) -> None:
        assert v.mask_card("4111-1111-1111-1111") == "************1111"

    def test_mask_strips_separators(self) -> None:
        assert v.mask_card("4111 1111 1111 1111") == "************1111"

    def test_mask_too_short_none(self) -> None:
        assert v.mask_card("12") is None
        assert v.mask_card("") is None

    def test_card_brands_list(self) -> None:
        assert v.card_brands() == ["amex", "diners", "discover", "jcb", "mastercard", "visa"]


class TestUrl:
    def test_valid(self) -> None:
        assert v.is_valid_url("https://example.com/path") is True

    def test_normalize_lowercases_and_strips_default_port(self) -> None:
        assert v.normalize_url("HTTP://Example.com:80/Path?q=1") == "http://example.com/Path?q=1"

    def test_normalize_keeps_nondefault_port(self) -> None:
        assert v.normalize_url("https://Example.com:8443/x") == "https://example.com:8443/x"

    def test_host(self) -> None:
        assert v.url_host("https://WWW.Example.com/a") == "www.example.com"

    def test_no_scheme_invalid(self) -> None:
        assert v.is_valid_url("example.com") is False
        assert v.normalize_url("example.com") is None

    def test_mailto_invalid(self) -> None:
        assert v.is_valid_url("mailto:a@b.com") is False

    def test_garbage_invalid(self) -> None:
        assert v.is_valid_url("not a url") is False
        assert v.url_host("not a url") is None

    def test_empty_invalid(self) -> None:
        assert v.is_valid_url("") is False

    def test_userinfo_preserved(self) -> None:
        assert v.normalize_url("http://User@Example.com/p") == "http://User@example.com/p"


class TestPostal:
    def test_us(self) -> None:
        assert v.is_valid_postal_code("90210", "US") is True
        assert v.is_valid_postal_code("90210-1234", "US") is True
        assert v.is_valid_postal_code("9021", "US") is False

    def test_ca(self) -> None:
        assert v.is_valid_postal_code("K1A 0B1", "CA") is True
        assert v.is_valid_postal_code("K1A0B1", "CA") is True
        assert v.is_valid_postal_code("123 456", "CA") is False

    def test_gb(self) -> None:
        assert v.is_valid_postal_code("SW1A 1AA", "GB") is True
        assert v.is_valid_postal_code("INVALID", "GB") is False

    def test_de_fr_simple(self) -> None:
        assert v.is_valid_postal_code("10115", "DE") is True
        assert v.is_valid_postal_code("75008", "FR") is True
        assert v.is_valid_postal_code("ABCDE", "DE") is False

    def test_nl(self) -> None:
        assert v.is_valid_postal_code("1234 AB", "NL") is True
        assert v.is_valid_postal_code("1234", "NL") is False

    def test_jp_in_br(self) -> None:
        assert v.is_valid_postal_code("100-0001", "JP") is True
        assert v.is_valid_postal_code("110 001", "IN") is True
        assert v.is_valid_postal_code("01310-100", "BR") is True

    def test_case_insensitive_country(self) -> None:
        assert v.is_valid_postal_code("90210", "us") is True

    def test_unknown_country_raises(self) -> None:
        with pytest.raises(ValueError):
            v.is_valid_postal_code("90210", "ZZ")

    def test_supported_countries(self) -> None:
        countries = v.supported_postal_countries()
        assert set(countries) == {"US", "CA", "GB", "DE", "FR", "NL", "AU", "JP", "IN", "BR"}
