# CLAUDE.md — vgi-conform

Contributor/agent notes. User-facing docs live in `README.md`; this is the
"how it's built and where the sharp edges are" companion.

## What this is

A [VGI](https://query.farm) worker that validates **and** normalizes real-world
structured-data fields — **email, phone, IBAN, VAT, credit card, URL, postal
code** — as DuckDB scalar functions, plus two discovery table functions. Backed
by `phonenumbers` (Apache-2.0), `python-stdnum` (**LGPL-2.1** — see below), and
`email-validator` (CC0). `conform_worker.py` assembles every function into one
`conform` catalog (single `main` schema) over stdio. Sibling style/tooling to
`vgi-calendar`.

## Layout

```
conform_worker.py      repo-root stdio entry point; PEP 723 inline deps; main()
vgi_conform/
  validators.py        pure validation/normalization logic; no Arrow/VGI; unit-testable
  scalars.py           per-row scalars (arity overloads for region/country)
  tables.py            discovery table functions: supported_phone_regions, card_brands
  schema_utils.py      pa.Field comment / column-doc helper
tests/                 pytest: test_validators (pure), test_tables (in-proc), test_scalars (Client RPC)
test/sql/*.test        haybarn-unittest sqllogictest — authoritative E2E
Makefile               test / test-unit / test-sql / lint
```

To add a function: implement the logic in `validators.py` (pure, total — never
raises on garbage; returns `None` for "invalid"), wrap it as a scalar or table
function in the matching module, register it in `conform_worker.py`'s
`_FUNCTIONS`.

## Scalars vs table functions — THE core convention (read first)

The VGI SDK makes **scalar functions positional-only**: `name := value` named
args are rejected for scalars and only work on table functions. This drove the
whole function-shape split here:

- **Per-row functions are scalars with arity overloads** so they work inline in a
  projection (`SELECT is_valid_phone(phone) FROM contacts`). Where a function has
  an optional `region` (phone) or `country` (VAT/postal), each arity is its own
  `ScalarFunction` subclass sharing the `Meta.name`:
  `is_valid_phone(text)` (region defaults to `'US'`) / `is_valid_phone(text,
  region)`. Same for the phone formatters, `phone_region`, `phone_type`,
  `is_valid_vat`, `format_vat`. (`is_valid_postal_code(text, country)` is *not*
  overloaded — country is required.)
- **Set-returning functions are table functions** (here, discovery only):
  `supported_phone_regions()`, `card_brands()`.

If you're tempted to give a scalar a `region :=` arg, you can't — add an overload
class instead. Don't try to build the overload classes from a factory function:
a nested `class Meta:` body cannot reference an enclosing-scope variable
(`name = name` raises `NameError` — the class body is not a closure), so each
overload is written out explicitly. It's verbose but boringly correct.

## Sharp edges (learned the hard way)

1. **`haybarn-unittest` skips `require vgi`.** Under haybarn the extension is not
   autoloaded for `require`, so a `.test` using `require vgi` is silently
   SKIPPED. Use an explicit `statement ok` / `LOAD vgi;` instead (every `.test`
   here already does). `LOAD vgi` also works under the locally-built vgi unittest.
2. **NULL vs invalid vs error — three distinct outcomes.** NULL input → NULL
   output everywhere. Invalid (non-NULL) input → `false` for `is_valid_*`, `NULL`
   for formatters/extractors/`normalize_*` (never an error). The **one** function
   that errors is `is_valid_postal_code(text, country)` on an **unknown country**
   — it raises `ValueError` (surfaced as a DuckDB error) so a country typo isn't
   mistaken for an invalid code. SQL covers this with a `statement error` block.
3. **Email validation is offline — no DNS.** `email-validator` is called with
   `check_deliverability=False`, so it's purely syntactic + normalizing. This is
   deliberate: the worker stays hermetic and deterministic (no network, no flaky
   tests). `normalize_email` lower-cases the domain but, per the library, leaves
   the local-part case intact (`Test@Example.COM` → `Test@example.com`).
4. **`phonenumbers` parse exceptions must be swallowed.** `phonenumbers.parse`
   raises `NumberParseException` on junk; `validators._parse_phone` catches it and
   returns `None` so nothing ever crashes the worker. Validity also requires
   `is_valid_number` (a parseable-but-bogus number is still invalid).
5. **Card brand ≠ Luhn.** `card_brand` classifies by IIN prefix + length only and
   does **not** require a passing checksum (so you can tag malformed PANs);
   `is_valid_card` is the Luhn check. Keep them independent.
6. **The unit suite can pass while the RPC path is broken.** `test_validators.py`
   calls pure functions directly; only `test_scalars.py` (real `vgi.client.Client`
   subprocess) and `test/sql/*.test` (real `ATTACH`+`SELECT`) exercise the wire.
   **Run the SQL suite** — it's authoritative.

## `python-stdnum` is LGPL-2.1 (licensing note)

`python-stdnum` (IBAN / EU-VAT / Luhn backend) is **LGPL-2.1**. We use it as an
**unmodified, separately pip-installed dependency** — imported, never vendored or
patched. That's the "using the library" case, not "modifying" it, so
**vgi-conform's own code stays MIT and is fine for commercial use**. The standard
LGPL relink/replace obligation is satisfied automatically because the package is
an ordinary, swappable PyPI dependency (a recipient can `pip install` a different
version). If you ever vendor or patch `python-stdnum`, those changes must be
offered under the LGPL — don't do that without intent. `phonenumbers` is
Apache-2.0 and `email-validator` is CC0, both permissive with no such caveat.

## Coverage caveats

- **Postal codes are intentionally modest**: a per-country regex table for ~10
  countries (US, CA, GB, DE, FR, NL, AU, JP, IN, BR), a format check, not
  authoritative deliverability validation. `validators.supported_postal_countries()`
  is the source of truth; extend `_POSTAL_PATTERNS` to add a country.
- **VAT**: the no-`country` form expects the EU-prefixed number (`stdnum.eu.vat`);
  the `country` overload dispatches to `stdnum.<cc>.vat` for the national number,
  falling back to the EU validator when no national module exists.
- Validation is only as complete as the underlying libraries' coverage.

## Testing

```sh
uv run pytest -q              # unit: pure logic + in-proc tables + Client RPC scalars
make test-sql                 # E2E: haybarn-unittest over test/sql/*  (authoritative)
make test                     # both
uv run ruff check . && uv run mypy vgi_conform/
```

`make test-sql` sets `VGI_CONFORM_WORKER="uv run --python 3.13
conform_worker.py"`, puts `~/.local/bin` on PATH, and runs `haybarn-unittest
--test-dir . "test/sql/*"`. Install the runner once with
`uv tool install haybarn-unittest`. CI (`.github/workflows/ci.yml`) runs unit +
lint + a gated `e2e` job that installs haybarn-unittest and runs `make test-sql`.

Everything is pure/offline (no network, no DNS, no model downloads), so the suite
is fast and hermetic.
