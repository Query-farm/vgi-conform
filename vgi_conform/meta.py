"""Per-object discoverability metadata helpers for the conform worker.

`vgi-lint-check` (strict profile) requires every function and table to carry a
small set of discoverability tags, in addition to the catalog/schema tags set in
:mod:`conform_worker`:

- ``vgi.title`` (VGI124)            -- human-friendly display name. Must NOT
  normalize-equal the machine name (lowercase + strip non-alphanumeric), or
  VGI125 fires; every title here adds at least one extra word.
- ``vgi.doc_llm`` (VGI112)          -- a Markdown narrative aimed at an LLM/agent
  audience: what it does, when to use it, inputs/outputs, edge cases.
- ``vgi.doc_md`` (VGI113)           -- a Markdown narrative for human docs:
  overview + usage + notes.
- ``vgi.keywords`` (VGI126/VGI138)  -- search terms / synonyms, serialized as a
  JSON array of strings (``["a", "b"]``), NOT a comma-separated string.

Per-object ``vgi.source_url`` is intentionally **not** emitted: ``source_url`` is
catalog-level provenance (set once on the catalog via the ``Catalog(source_url=)``
argument); repeating it on every function/schema is redundant (VGI139).

:func:`function_tags` assembles these (plus any extra tags, e.g.
``vgi.result_columns_md`` for table functions) into the ``dict`` a function
exposes as ``class Meta: tags = ...``.
"""

from __future__ import annotations

import json


def keywords_json(keywords: str) -> str:
    """Serialize comma-separated keywords as a JSON array of strings (VGI138).

    Args:
        keywords: Comma-separated search terms / synonyms, e.g.
            ``"email, validate email, address check"``.

    Returns:
        A JSON array string such as
        ``'["email", "validate email", "address check"]'``, with each term
        trimmed and empty entries dropped.
    """
    terms = [t.strip() for t in keywords.split(",") if t.strip()]
    return json.dumps(terms)


def function_tags(
    *,
    title: str,
    description_llm: str,
    description_md: str,
    keywords: str,
    relative_path: str,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Assemble the per-object discoverability tag dict for a ``class Meta``.

    Args:
        title: Human display name (VGI124); must differ from the machine name.
        description_llm: Markdown narrative for an LLM/agent audience (VGI112).
        description_md: Markdown narrative for human docs (VGI113).
        keywords: Comma-separated search terms / synonyms; emitted as a JSON
            array of strings under ``vgi.keywords`` (VGI126/VGI138).
        relative_path: Unused; retained for call-site compatibility. Per-object
            ``vgi.source_url`` is no longer emitted (VGI139) -- ``source_url`` is
            set once on the catalog instead.
        extra: Optional additional tags to merge in (e.g.
            ``vgi.result_columns_md`` or ``vgi.executable_examples``).

    Returns:
        A ``dict[str, str]`` suitable for ``class Meta: tags = ...``.
    """
    del relative_path  # per-object source_url dropped (VGI139); kept for callers
    tags = {
        "vgi.title": title,
        "vgi.doc_llm": description_llm,
        "vgi.doc_md": description_md,
        "vgi.keywords": keywords_json(keywords),
    }
    if extra:
        tags.update(extra)
    return tags
