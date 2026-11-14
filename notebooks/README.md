# Contact-field validation notebooks

[01 · Normalized fields are not verified contacts](01_normalized_fields_are_not_verified_contacts.ipynb)
uses a twelve-row synthetic import to validate and normalize email, phone and URL
fields through VGI. Visible SQL preserves missing and invalid values, reports
normalization groups and compares country-specific phone parsing with a global
US assumption. Two charts show field outcomes and the effect of parsing context.

## Run from this directory

Install [uv](https://docs.astral.sh/uv/) and ensure `uvx` is on PATH:

```sh
cd notebooks
uv sync --locked
uv run --locked python execute.py
```

In a notebook editor, select `notebooks/.venv/bin/python` as the kernel and run
all cells. The complete notebook directory also works outside the repository;
no local worker source, build or root environment is used. Its locked Python
3.13–3.14 environment uses Haybarn 2.0.0rc11, JupySQL, Seaborn and Matplotlib.
The worker runs in a separate Python 3.13 environment provisioned by `uvx`.

The connection is a literal, visible SQL cell:

```sql
INSTALL vgi FROM community;
LOAD vgi;
ATTACH 'conform' (TYPE vgi,
 LOCATION 'uvx --python 3.13 --with phonenumbers==9.0.43 --with python-stdnum==2.2 --with email-validator==2.3.0 --with vgi-python==0.51.0 --with vgi-rpc==0.53.1 --from git+https://github.com/Query-farm/vgi-conform@v0.4.0 vgi-conform-worker');
```

The public Git tag, validation libraries and VGI runtime are pinned. Initial
downloads need network access; the field checks make no DNS, web, email or phone
requests. The runner permits 600 seconds per cell for first-run setup. To upgrade,
change the visible pins and revalidate both contexts. Parameters and SQL remain
expanded; imports, presentation code and cleanup are folded, preserving useful
outputs. Official local Strata Sun branding appears at the top and final bottom,
with the VGI logo and links near the top.

## One-parameter experiment

`PHONE_CONTEXT` accepts `"row_country"` (default) or `"US"`. Both comparisons are
materialized each run; the parameter selects the main report and chart outline.
The raw inputs and email/URL checks stay fixed.

```sh
uv run --locked python execute.py --parameters '{"PHONE_CONTEXT":"US"}' \
  --output-dir validation/us-context
```

The runner rejects overrides without a separate destination, unknown parameter
names and source-directory overwrites. A failed execution leaves the last saved
successful default unchanged. Experiment copies include their branding, helpers,
README and locked environment. Generated review PNGs and experiments under
`validation/` are ignored; the main notebook retains its successful outputs.

## What the example establishes

All data is embedded in visible SQL. The records are synthetic, and the phone
strings are format examples rather than people to contact. Empty strings remain
invalid; SQL NULL remains missing. Both original and normalized strings survive.
The worker's boolean validity and normalized-value availability are checked
alongside row conservation, idempotence and context independence.

The published scalar overloads require constant region arguments. Explicit US
and GB branches select a constant-argument call for each row, with a guard
rejecting unknown or missing country contexts. A broader import should add and
verify appropriate branches instead of silently assigning a default country.
The returned phone region is a separate attribute from the supplied parsing
context; the illustrated mismatch does not establish that a record is wrong.

Email validation is syntactic and normalization retains local-part case. URL
normalization retains path case, query order and fragments while normalizing
scheme, host and default port. Counts of distinct raw strings use only valid
values, making them comparable to distinct normalized strings. Repeated
normalized values are candidate field matches, not proof of person identity.
The public v0.4.0 URL parser rejects the root-path URL `https://example.net/`
in record 06, although it is an absolute URL. The notebook explicitly labels
this release limitation: “Invalid” is the worker verdict and is not a universal
URL-validity rule. The input is retained for review.

No result establishes deliverability, number assignment or ownership. The
small fixture is not an estimate of real-world data quality or library coverage.

References: [worker documentation](https://github.com/Query-farm/vgi-conform),
[pinned v0.4.0 source](https://github.com/Query-farm/vgi-conform/tree/v0.4.0).
