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
- ``vgi.keywords`` (VGI126)         -- comma-separated search terms / synonyms.
- ``vgi.source_url`` (VGI128)       -- link to the implementing source file.

:func:`function_tags` assembles all of these (plus any extra tags, e.g.
``vgi.result_columns_md`` for table functions) into the ``dict`` a function
exposes as ``class Meta: tags = ...``.
"""

from __future__ import annotations

_REPO_BLOB = "https://github.com/Query-farm/vgi-conform/blob/main"


def source_url(relative_path: str) -> str:
    """Build the canonical GitHub blob URL for a source file under the repo root.

    Args:
        relative_path: Path relative to the repository root, e.g.
            ``"vgi_conform/scalars.py"``.

    Returns:
        The ``https://github.com/Query-farm/vgi-conform/blob/main/<path>`` URL.
    """
    return f"{_REPO_BLOB}/{relative_path}"


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
        keywords: Comma-separated search terms / synonyms (VGI126).
        relative_path: Source file path relative to the repo root (VGI128).
        extra: Optional additional tags to merge in (e.g. ``vgi.result_columns_md`` or
            ``vgi.executable_examples``).

    Returns:
        A ``dict[str, str]`` suitable for ``class Meta: tags = ...``.
    """
    tags = {
        "vgi.title": title,
        "vgi.doc_llm": description_llm,
        "vgi.doc_md": description_md,
        "vgi.keywords": keywords,
        "vgi.source_url": source_url(relative_path),
    }
    if extra:
        tags.update(extra)
    return tags
