# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python[http]>=0.8.3",
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

_CONFORM_CATALOG = Catalog(
    name="conform",
    default_schema="main",
    schemas=[
        Schema(
            name="main",
            comment="Validate + normalize phone/email/IBAN/VAT/card/URL/postal fields for SQL",
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
