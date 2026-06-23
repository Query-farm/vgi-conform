"""End-to-end tests for the per-row scalar conform functions.

These spawn ``conform_worker.py`` as a subprocess via ``vgi.client.Client`` and
call each scalar exactly as DuckDB would after ``ATTACH``, exercising the arity
overloads (``is_valid_phone(text)`` / ``(text, region)`` and the like). The
``text`` column travels in the input batch (a ``Param``); only the constant
``region`` / ``country`` arguments go in ``positional``.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa
import pytest
from vgi import Arguments
from vgi.client import Client

_WORKER = str(Path(__file__).resolve().parent.parent / "conform_worker.py")


@pytest.fixture(scope="module")
def client() -> Iterator[Client]:
    # Current interpreter (deps already installed) + worker_limit=1 so output
    # order matches input order for deterministic per-row assertions.
    with Client(f"{sys.executable} {_WORKER}", worker_limit=1) as c:
        yield c


def _scalar(client: Client, name: str, values: list, *, positional: list[pa.Scalar] | None = None) -> list:
    batch = pa.RecordBatch.from_pydict({"t": pa.array(values, type=pa.string())})
    results = list(
        client.scalar_function(
            function_name=name,
            input=iter([batch]),
            arguments=Arguments(positional=positional or []),
        )
    )
    return results[0]["result"].to_pylist()


class TestEmail:
    def test_is_valid(self, client: Client) -> None:
        assert _scalar(client, "is_valid_email", ["a@b.com", "nope", None]) == [True, False, None]

    def test_normalize(self, client: Client) -> None:
        assert _scalar(client, "normalize_email", ["Test@Example.COM"]) == ["Test@example.com"]

    def test_domain(self, client: Client) -> None:
        assert _scalar(client, "email_domain", ["a@Example.com"]) == ["example.com"]


class TestPhone:
    def test_default_region(self, client: Client) -> None:
        assert _scalar(client, "is_valid_phone", ["202-456-1111", "garbage"]) == [True, False]

    def test_e164_default(self, client: Client) -> None:
        assert _scalar(client, "format_phone_e164", ["202-456-1111"]) == ["+12024561111"]

    def test_region_overload(self, client: Client) -> None:
        assert _scalar(client, "is_valid_phone", ["07911 123456"], positional=[pa.scalar("GB")]) == [True]
        assert _scalar(client, "format_phone_e164", ["07911 123456"], positional=[pa.scalar("GB")]) == ["+447911123456"]

    def test_wrong_region_null(self, client: Client) -> None:
        assert _scalar(client, "format_phone_e164", ["07911 123456"], positional=[pa.scalar("US")]) == [None]

    def test_type_and_region(self, client: Client) -> None:
        assert _scalar(client, "phone_type", ["07911 123456"], positional=[pa.scalar("GB")]) == ["mobile"]


class TestIban:
    def test_valid_and_format(self, client: Client) -> None:
        assert _scalar(client, "is_valid_iban", ["GB82 WEST 1234 5698 7654 32"]) == [True]
        assert _scalar(client, "format_iban", ["GB82WEST12345698765432"]) == ["GB82 WEST 1234 5698 7654 32"]
        assert _scalar(client, "iban_country", ["GB82WEST12345698765432"]) == ["GB"]

    def test_bad_checksum(self, client: Client) -> None:
        assert _scalar(client, "is_valid_iban", ["GB00WEST12345698765432"]) == [False]


class TestVat:
    def test_eu_default(self, client: Client) -> None:
        assert _scalar(client, "is_valid_vat", ["DE136695976", "US123"]) == [True, False]

    def test_country_overload(self, client: Client) -> None:
        assert _scalar(client, "is_valid_vat", ["136695976"], positional=[pa.scalar("DE")]) == [True]


class TestCard:
    def test_luhn(self, client: Client) -> None:
        assert _scalar(client, "is_valid_card", ["4111111111111111", "4111111111111112"]) == [True, False]

    def test_brand_and_mask(self, client: Client) -> None:
        assert _scalar(client, "card_brand", ["4111111111111111"]) == ["visa"]
        assert _scalar(client, "mask_card", ["4111-1111-1111-1111"]) == ["************1111"]


class TestUrl:
    def test_valid_and_normalize(self, client: Client) -> None:
        assert _scalar(client, "is_valid_url", ["https://x.com", "nope"]) == [True, False]
        assert _scalar(client, "normalize_url", ["HTTP://Example.com:80/Path"]) == ["http://example.com/Path"]
        assert _scalar(client, "url_host", ["https://WWW.Example.com/a"]) == ["www.example.com"]


class TestPostal:
    def test_valid(self, client: Client) -> None:
        assert _scalar(client, "is_valid_postal_code", ["90210"], positional=[pa.scalar("US")]) == [True]
        assert _scalar(client, "is_valid_postal_code", ["K1A 0B1"], positional=[pa.scalar("CA")]) == [True]

    def test_unknown_country_errors(self, client: Client) -> None:
        from vgi.client import ClientError

        with pytest.raises(ClientError):
            _scalar(client, "is_valid_postal_code", ["90210"], positional=[pa.scalar("ZZ")])
