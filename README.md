<p align="center">
  <img src="https://raw.githubusercontent.com/Query-farm/vgi/main/docs/vgi-logo.png" alt="Vector Gateway Interface (VGI)" width="320">
</p>

<p align="center"><em>A <a href="https://query.farm">Query.Farm</a> VGI worker for DuckDB.</em></p>

# Validate & Normalize Phone, Email, IBAN, VAT, Card & URL in DuckDB

> **vgi-conform** · a [Query.Farm](https://query.farm) VGI worker

[![CI](https://github.com/Query-farm/vgi-conform/actions/workflows/ci.yml/badge.svg)](https://github.com/Query-farm/vgi-conform/actions/workflows/ci.yml)

A [VGI](https://query.farm) worker that brings **field validation and
normalization** into DuckDB/SQL. It checks *and* canonicalizes the real-world
structured-data fields that show up in every dataset — **email, phone, IBAN,
VAT, credit card, URL, postal code** — as plain SQL scalar functions, backed by
battle-tested libraries: [`phonenumbers`](https://pypi.org/project/phonenumbers/)
(Apache-2.0), [`python-stdnum`](https://pypi.org/project/python-stdnum/)
(LGPL-2.1) and [`email-validator`](https://pypi.org/project/email-validator/)
(CC0).

```sql
INSTALL vgi FROM community; LOAD vgi;
ATTACH 'conform' (TYPE vgi, LOCATION 'uv run conform_worker.py');

SELECT conform.is_valid_email('a@b.com');                  -- true
SELECT conform.normalize_email('Test@Example.COM');        -- 'test@example.com'
SELECT conform.format_phone_e164('202-456-1111');          -- '+12024561111' (region 'US')
SELECT conform.format_phone_e164('07911 123456', 'GB');    -- '+447911123456'
SELECT conform.is_valid_iban('GB82 WEST 1234 5698 7654 32');-- true
SELECT conform.iban_country('GB82WEST12345698765432');     -- 'GB'
SELECT conform.is_valid_vat('DE136695976');                -- true
SELECT conform.card_brand('4111111111111111');             -- 'visa'
SELECT conform.mask_card('4111-1111-1111-1111');           -- '************1111'
SELECT conform.normalize_url('HTTP://Example.com:80/Path');-- 'http://example.com/Path'
SELECT conform.is_valid_postal_code('90210', 'US');        -- true
```

Everything runs **offline and deterministically** — there are no network or DNS
lookups (email validation is syntactic + normalizing only), so the worker is
fast and hermetic, and the same input always gives the same answer.

## Scalars (per-row) vs. table functions (discovery)

The split follows what the VGI SDK allows for each function shape:

* **Scalars** take **positional** arguments only and resolve overloads by
  *arity* (DuckDB's `name := value` syntax is a table-function/macro feature, not
  a scalar one). Every per-row answer is a **scalar**, so it works inline in any
  projection or predicate. Where a function takes an optional `region` (phone) or
  `country` (VAT), that argument is an extra positional **arity overload**:

  ```sql
  SELECT is_valid_phone(phone)                FROM contacts;  -- region defaults to 'US'
  SELECT is_valid_phone(phone, 'GB')          FROM contacts;  -- explicit region
  SELECT id, normalize_email(email)           FROM users;
  SELECT pan, mask_card(pan)                  FROM payments;
  ```

* **Table functions** return *many* rows (here, discovery / reference data):
  `supported_phone_regions()` and `card_brands()`.

  ```sql
  SELECT * FROM conform.supported_phone_regions() ORDER BY region;
  SELECT * FROM conform.card_brands() ORDER BY brand;
  ```

**NULL semantics.** A NULL input yields NULL output for every function.
`is_valid_*` predicates return `false` for invalid (non-NULL) input; formatters /
extractors / `normalize_*` return `NULL` for invalid input (never an error),
*except* `is_valid_postal_code(text, country)`, which raises for an **unknown
country** (see Postal codes below).

## Function catalog

| Function | Form | Signature | Returns |
| --- | --- | --- | --- |
| `is_valid_email` | scalar | `(text)` | `BOOLEAN` |
| `normalize_email` | scalar | `(text)` | `VARCHAR` (NULL if invalid) |
| `email_domain` | scalar | `(text)` | `VARCHAR` (NULL if invalid) |
| `is_valid_phone` | scalar | `(text[, region])` | `BOOLEAN` |
| `format_phone_e164` | scalar | `(text[, region])` | `VARCHAR` (NULL if invalid) |
| `format_phone_national` | scalar | `(text[, region])` | `VARCHAR` (NULL if invalid) |
| `format_phone_international` | scalar | `(text[, region])` | `VARCHAR` (NULL if invalid) |
| `phone_region` | scalar | `(text[, region])` | `VARCHAR` (NULL if invalid) |
| `phone_type` | scalar | `(text[, region])` | `VARCHAR` (`mobile`/`fixed_line`/…) |
| `is_valid_iban` | scalar | `(text)` | `BOOLEAN` |
| `format_iban` | scalar | `(text)` | `VARCHAR` (grouped 4s, NULL if invalid) |
| `iban_country` | scalar | `(text)` | `VARCHAR` (NULL if invalid) |
| `is_valid_vat` | scalar | `(text[, country])` | `BOOLEAN` |
| `format_vat` | scalar | `(text[, country])` | `VARCHAR` (NULL if invalid) |
| `is_valid_card` | scalar | `(text)` | `BOOLEAN` (Luhn) |
| `card_brand` | scalar | `(text)` | `VARCHAR` (`visa`/`mastercard`/…, NULL if none) |
| `mask_card` | scalar | `(text)` | `VARCHAR` (e.g. `************1234`) |
| `is_valid_url` | scalar | `(text)` | `BOOLEAN` |
| `normalize_url` | scalar | `(text)` | `VARCHAR` (NULL if invalid) |
| `url_host` | scalar | `(text)` | `VARCHAR` (NULL if invalid) |
| `is_valid_postal_code` | scalar | `(text, country)` | `BOOLEAN` (raises on unknown country) |
| `supported_phone_regions` | table | `()` | `(region VARCHAR, country_code INT)` |
| `card_brands` | table | `()` | `(brand VARCHAR)` |

The phone `region` default is `'US'`. The VAT `country` overload validates the
*national* (unprefixed) number via `stdnum.<cc>.vat`; the no-`country` form
validates the *EU-prefixed* number (e.g. `'DE136695976'`) via `stdnum.eu.vat`.

### Email

Validation is **syntactic and normalizing only** — deliverability (DNS) checks
are deliberately disabled so the worker has no network dependency and is fully
deterministic. `normalize_email` lower-cases the domain (and applies the other
`email-validator` normalizations); `email_domain` returns the normalized domain.

```sql
SELECT email, normalize_email(email) AS clean, email_domain(email) AS domain
FROM users
WHERE is_valid_email(email);
```

### Phone

Phone numbers are parsed in a `region` (ISO-3166 alpha-2, default `'US'`).
Anything that fails to parse or isn't a valid number resolves to `false` /
`NULL` — `phonenumbers`' parse exceptions never surface as SQL errors. Use
`conform.supported_phone_regions()` to discover region codes and dialling codes.

```sql
SELECT format_phone_e164(phone, 'GB')      AS e164,
       phone_type(phone, 'GB')             AS line_type,
       phone_region(phone, 'GB')           AS belongs_to
FROM uk_contacts
WHERE is_valid_phone(phone, 'GB');
```

### IBAN

`is_valid_iban` includes the mod-97 checksum; `format_iban` pretty-prints the
IBAN into space-separated blocks of four; `iban_country` returns the leading
two-letter country code.

### VAT

`is_valid_vat(text)` validates an **EU country-prefixed** VAT number via
`stdnum.eu.vat`. `is_valid_vat(text, country)` validates a **national**
(unprefixed) number via the country-specific `stdnum.<cc>.vat` module, falling
back to the EU validator if no such module exists. `format_vat` returns the
compact (whitespace-stripped, upper-cased) number.

### Credit card

`is_valid_card` checks the Luhn checksum (`stdnum.luhn`) over a 12–19 digit
number. `card_brand` detects the brand (`visa`, `mastercard`, `amex`,
`discover`, `diners`, `jcb`) from the IIN prefix + length **without** requiring a
valid checksum, so you can tag obviously-malformed numbers too. `mask_card`
keeps the last four digits and masks the rest (`************1234`).

```sql
SELECT card_brand(pan) AS brand, mask_card(pan) AS masked
FROM payments
WHERE is_valid_card(pan);
```

### URL

A URL is **valid** when it is absolute (`scheme://host`). `normalize_url`
lower-cases the scheme and host and strips a default port (`:80` for http,
`:443` for https, …) while preserving the (case-sensitive) path/query/fragment;
`url_host` returns the lower-cased host.

### Postal codes

> **Modest, intentional coverage.** `is_valid_postal_code(text, country)` does a
> per-country **format** check (a regex), *not* an authoritative deliverability
> lookup, and covers ten major countries: **US, CA, GB, DE, FR, NL, AU, JP, IN,
> BR**. An **unknown country raises an error** (rather than silently returning
> `false`) so a typo in the country code is never mistaken for an invalid code.
> For exhaustive postal validation, pair this with a dedicated address service.

```sql
SELECT is_valid_postal_code('K1A 0B1', 'CA');   -- true
SELECT is_valid_postal_code('SW1A 1AA', 'GB');  -- true
SELECT is_valid_postal_code('1234', 'ZZ');      -- ERROR: unsupported postal-code country 'ZZ'
```

## Dependencies & licensing

| Component | License | Notes |
| --- | --- | --- |
| `vgi-conform` (this worker) | **MIT** | This repository's own code. |
| [`phonenumbers`](https://pypi.org/project/phonenumbers/) | **Apache-2.0** | Phone parse/validate/format. |
| [`python-stdnum`](https://pypi.org/project/python-stdnum/) | **LGPL-2.1** | IBAN / VAT / Luhn. **See the LGPL note below.** |
| [`email-validator`](https://pypi.org/project/email-validator/) | **CC0** (public domain) | Email syntax + normalization. |
| [`vgi-python`](https://github.com/Query-farm/vgi-python) | Query Farm Source-Available | The VGI SDK. |

### LGPL note for `python-stdnum`

`python-stdnum` is licensed under the **LGPL-2.1**. This worker uses it as an
**unmodified, separately-installed pip dependency** — it is imported, never
copied into or modified within this repository. Under the LGPL that is the
"using the library" case (not "modifying" it), so **`vgi-conform`'s own code
remains MIT and is fine for commercial use**. The standard LGPL obligation
applies: a recipient of a distributed bundle must be able to **relink or replace**
the LGPL component with a modified version — which is automatically satisfied
here because `python-stdnum` is resolved from PyPI as an ordinary, swappable
dependency (you can `pip install` a different version at any time). If you ever
vendor or patch `python-stdnum`, those changes must themselves be offered under
the LGPL.

Validation rules are only as complete as the underlying libraries' coverage for
a given country / number type; consult their docs for authoritative support
matrices.

## Local development

```sh
uv sync --all-extras     # create .venv with vgi-python + phonenumbers + stdnum + email-validator + dev tools
make test                # pytest (unit + integration) + SQL end-to-end
make test-unit           # pytest only
make test-sql            # DuckDB sqllogictest files via haybarn-unittest
uv run ruff check .      # lint
uv run mypy vgi_conform/
```

`tests/test_validators.py` covers the pure validation/normalization logic
(including a strong battery of error / edge cases — empty, garbage, bad
checksums, wrong-region phone, non-EU VAT, malformed URLs);
`tests/test_tables.py` drives the discovery table functions through the real
bind→init→process lifecycle in-process; `tests/test_scalars.py` spawns
`conform_worker.py` over the VGI client/RPC stack exactly as DuckDB would after
`ATTACH`. The `test/sql/*.test` files are DuckDB sqllogictest cases run by
[`haybarn-unittest`](https://pypi.org/project/haybarn-unittest/)
(`uv tool install haybarn-unittest`) against a real `ATTACH` + `SELECT`.

## Layout

```
conform_worker.py        entry point; assembles the `conform` catalog (inline uv script metadata)
Makefile                 test / test-unit / test-sql targets
vgi_conform/
  validators.py          pure validation + normalization logic (no Arrow/VGI)
  scalars.py             per-row scalars (arity overloads for region/country)
  tables.py              discovery table functions: supported_phone_regions, card_brands
  schema_utils.py        Arrow field/comment helper
tests/
  harness.py             in-process bind→init→process driver
  test_validators.py     pure-logic unit + error/edge tests
  test_tables.py         table-function integration tests
  test_scalars.py        per-row scalar overloads via vgi.client.Client
test/sql/
  *.test                 DuckDB sqllogictest end-to-end cases (haybarn-unittest)
```

---

## Authorship & License

Written by [Query.Farm](https://query.farm).

Copyright 2026 Query Farm LLC - https://query.farm

