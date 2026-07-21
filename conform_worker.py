# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python[http]>=0.16.1",
#     "phonenumbers>=9.0",
#     "python-stdnum>=2.2",
#     "email-validator>=2.3",
# ]
# ///
"""Repo-root stdio entry point for the vgi-conform worker.

DuckDB (and the CI integration suite) spawn this script directly via ``uv run``::

    INSTALL vgi FROM community; LOAD vgi;
    ATTACH 'conform' (TYPE vgi, LOCATION 'uv run conform_worker.py');

    SELECT conform.is_valid_email('a@b.com');                 -- true
    SELECT conform.normalize_email('Test@Example.COM');       -- 'test@example.com'
    SELECT conform.format_phone_e164('202-456-1111');         -- '+12024561111' (region 'US')
    SELECT conform.is_valid_iban('GB82 WEST 1234 5698 7654 32');
    SELECT conform.card_brand('4111111111111111');            -- 'visa'
    SELECT conform.mask_card('4111-1111-1111-1111');          -- '************1111'
    SELECT * FROM conform.supported_phone_regions();

The catalog assembly and the ``ConformWorker`` class live in
:mod:`vgi_conform.worker` so they ship inside the installed wheel and can be
served by the ``vgi-conform-worker`` console script and ``vgi-serve
vgi_conform.worker:ConformWorker --http`` (the paths the Docker image uses).
This file is a thin shim that re-exports them for the PEP 723 ``uv run`` entry
point, so ``uv run conform_worker.py`` keeps working unchanged.
"""

from __future__ import annotations

from vgi_conform.worker import ConformWorker, main

__all__ = ["ConformWorker", "main"]


if __name__ == "__main__":
    main()
