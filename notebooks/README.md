# Field Validation notebooks

[01 · Normalized fields are not verified contacts](01_normalized_fields_are_not_verified_contacts.ipynb)
uses twelve synthetic rows to examine email, phone and URL validation and normalization.
Visible SQL retains invalid and missing inputs, compares normalization groups, groups
at domain/host grain, and derives national/international phone displays from canonical
E.164 values. Two SVG charts show field outcomes and the effect of phone parsing context.
No email, phone number or URL is contacted.

## Run locally or in Colab

Install Git and [uv](https://docs.astral.sh/uv/), then run from this directory:

```sh
uv sync --locked
uv run --locked vgi-notebooks 01_normalized_fields_are_not_verified_contacts.ipynb --timeout 600
```

Use this directory's `.venv/bin/python` in a notebook editor, or use the notebook's
**Open in Colab** badge and run all cells. Its bootstrap installs only the base
[shared package v0.3.17](https://github.com/Query-farm/vgi-example-notebooks/tree/v0.3.17),
preserving compatible preloaded pandas/Matplotlib/IPython versions. Local publication
adds `[runner]`; Colab does not. A fresh preloaded Python 3.12 kernel is tested with
this complete notebook; hosted Colab is not manually exercised.

The notebook file runs without worker source or companion Python files. Shared
presentation supplies unchanged linked branding, the proper catalog title/repository
heading, footer links and SVG figures. Parameters and SQL stay visible; Python setup,
plots and cleanup are folded. GitHub shows linked SVG assets; reruns show native SVG.

## Released worker, separate environment

```sql
INSTALL vgi FROM community;
LOAD vgi;
ATTACH 'conform' (TYPE vgi,
 LOCATION 'uvx --python 3.13 --from git+https://github.com/Query-farm/vgi-conform@v0.4.0 vgi-conform-worker');
```

This fetches public **v0.4.0** (`6aa89374cc0cd818b4148c8284edd20c8cc2a9ab`) in
an isolated worker environment. `uv` provisions Python 3.13 if needed. The tested
resolver supplies phonenumbers **9.0.43**, python-stdnum **2.2**, email-validator
**2.4.0**, VGI Python **0.51.1**, VGI RPC **0.53.1** and PyArrow **26.0.1**. The source
tag is pinned; transitive dependencies follow its declarations and may change on
future fresh resolutions. No `--with` overrides or validation-library installations
in the notebook kernel are needed. Haybarn **2.0.0rc11** and shared tooling are
locked separately here.

Initial downloads need network access. The checks themselves make no DNS, web,
email or phone requests. SQL starts with an empty temporary secret directory and
persistent secrets disabled. No credentials or account operations are involved.
Change the visible release tag and rerun both parameter settings when upgrading.

## One-parameter experiment

`PHONE_CONTEXT` accepts `"row_country"` (default) or `"US"`. Both are materialized
in every run; the parameter selects the main report, display table and chart outline.

```sh
uv run --locked vgi-notebooks 01_normalized_fields_are_not_verified_contacts.ipynb \
  --parameters '{"PHONE_CONTEXT":"US"}' --output-dir validation/us-context --timeout 600
```

Predict which rows change before running. The two national GB strings should lose
their usable normalized values under the US assumption; explicit international
forms should agree. Compare the Phone bar, normalization groups, phone display
table and outlined matrix column. Inputs, email/URL checks and domain/host groups
stay fixed. Reset to `"row_country"`.

The runner requires a separate destination for overrides and rejects unknown
parameters or source-directory overwrites. A failed run preserves the last successful
default. Detached copies include chart assets and a README. Logs, review PNGs and
experiment copies are ignored; successful notebook outputs, coverage evidence and
`charts/` SVG assets are published.

## What the example establishes

All twelve rows are invented teaching inputs. Phone strings are format examples,
not people to contact. NULL remains missing, empty text remains invalid, and both
original and normalized strings survive. A passing format check does not establish
reachability, ownership or identity; matching normalized fields do not prove two
rows describe one person.

The worker's `supported_phone_regions()` result establishes the US/GB contexts
used by the example. The released scalar overloads require constant region arguments,
so explicit branches choose constant US or GB calls for each row. An input guard
rejects missing, unsupported or unimplemented contexts before those branches run.
A broader import should add and verify branches, not silently guess a country.

Returned number region is separate from supplied parsing context. The German
international number on a US-labeled row illustrates why a mismatch alone does not
establish invalidity. National/international display forms are derived from valid
E.164 values that already carry a calling code. National display can omit that code;
keep E.164 and returned region alongside it. International displays are checked for
round-trip agreement with the retained canonical value.

Email checks are syntactic and preserve local-part case while normalizing the domain.
URL normalization preserves path case, query order and fragments while normalizing
scheme, host and default port. Domain/host grouping is coarser than full normalized
values: a domain can contain multiple email local parts and a host can contain distinct
paths or query strings. The group tables retain source record IDs for inspection and
make no claim about organizational ownership.

The public v0.4.0 parser rejects the root-path URL `https://example.net/` in record 06,
although it is an absolute URL. “Invalid” means the released worker's verdict, not a
universal URL-validity rule. The raw input remains visible for review. Current source
retains this parser behavior; this notebook does not patch it.

Ten SQL invariants check row conservation, NULL/invalid distinctions, idempotence,
context independence, international-number behavior, cardinality, display round trips
and domain/host availability. These checks establish behavior for the supplied fixture
and tested library versions; the sample is not a real-world quality or coverage benchmark.

## Coverage evidence

[coverage.json](coverage.json) maps **12/24** logical public surfaces to visible
executed SQL and reviewed findings, meeting the half-surface target. Complete native
function/table/view exports reconcile the denominator; overloads and same-named
relation aliases count once, with no capability exclusions.

Released v0.4.0 and current public main `8f1c42f9a35a4de1b3b26511459662aa3ab4cec7`
have the same 24-name interface. Current main adds composed examples and corrects
metadata wording; `validators.py` and the selected computations are unchanged.
The current catalog was collected through its existing installed environment without
a build. Notebook execution uses the released worker: exact-runtime coverage is
**12 released / 0 current**, with **12/24 current-interface** coverage supported by
editorial compatibility review rather than a current-source notebook execution claim.

The other twelve surfaces remain explicitly uncovered: `card_brand`, `card_brands`,
`format_iban`, `format_vat`, `iban_country`, `is_valid_card`, `is_valid_iban`,
`is_valid_postal_code`, `is_valid_vat`, `mask_card`, `phone_type` and
`supported_postal_countries`. They need their own country, format or checksum context.

This notebook-only change reuses successful source CI
[43563369639](https://github.com/Query-farm/vgi-conform/actions/runs/43563369639).
Worker sources and root dependency locks remain unchanged. Notebook defaults,
experiment, fresh/preloaded bootstrap, chart review, runner guards, Ruff/format and
hash-bound coverage receipts are checked separately.
