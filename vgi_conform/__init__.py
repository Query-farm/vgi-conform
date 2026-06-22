"""Validate + normalize real-world structured data fields as a VGI worker.

The implementation is split so each concern stays focused:

- ``validators`` -- pure validation / normalization logic over
  ``phonenumbers``, ``python-stdnum``, ``email-validator`` and the stdlib; no
  Arrow or VGI dependency, directly unit-testable.
- ``scalars``    -- per-row VGI scalar functions (positional-only; optional
  ``region`` / ``country`` arguments are exposed as arity overloads).
- ``tables``     -- set-returning discovery table functions
  (``supported_phone_regions``, ``card_brands``).

``conform_worker.py`` at the repo root assembles these into the ``conform``
catalog and runs the worker over stdio (or HTTP).
"""

from __future__ import annotations

__version__ = "0.1.0"
