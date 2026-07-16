"""Deterministic, ATT&CK-aligned naming for created artefacts.

Central helper so every creation tool names consistently, and so the client can
be told the rule and follow it too. All names are lowercase snake_case with
unsafe characters stripped; collisions are resolved with a numeric suffix.

Schemes (section 7 of the brief):
  - Ability:   ``T####[.###]_<short_snake_desc>``   e.g. T1059.001_powershell_download_cradle
  - Adversary: ``<theme>_<short_desc>``             e.g. hyadina_ransomware_chain
  - Operation: ``op_<adversary>_<agentgroup>_<YYYYMMDD-HHMM>``

This file is original to the claudera plugin (Apache-2.0).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

_NON_SNAKE = re.compile(r"[^a-z0-9]+")
_TECHNIQUE_RE = re.compile(r"^T\d{4}(\.\d{3})?$")


def snake(text: str, max_words: int = 8) -> str:
    """Lowercase snake_case, unsafe characters stripped, optionally word-capped."""
    parts = [p for p in _NON_SNAKE.split((text or "").strip().lower()) if p]
    if max_words:
        parts = parts[:max_words]
    return "_".join(parts)


def normalize_technique_id(technique_id: str) -> str:
    """Normalise an ATT&CK technique id to ``T####`` / ``T####.###``.

    Accepts ``1059.001`` / ``t1059`` etc. Raises ValueError if it can't be made
    to fit the ATT&CK shape.
    """
    t = (technique_id or "").strip().upper()
    if t and not t.startswith("T"):
        t = "T" + t
    if not _TECHNIQUE_RE.match(t):
        raise ValueError(
            f"invalid ATT&CK technique id '{technique_id}': expected T#### or "
            f"T####.### (e.g. T1059 or T1059.001)"
        )
    return t


def ability_name(technique_id: str, description: str) -> str:
    tid = normalize_technique_id(technique_id)
    desc = snake(description)
    if not desc:
        raise ValueError("a description/summary is required to name an ability")
    return f"{tid}_{desc}"


def adversary_name(theme: str, description: str) -> str:
    theme_s = snake(theme, max_words=2)
    desc = snake(description)
    parts = [p for p in (theme_s, desc) if p]
    if not parts:
        raise ValueError("a theme and/or description is required to name an adversary")
    return "_".join(parts)


def operation_name(adversary: str, group: str, when: datetime | None = None) -> str:
    when = when or datetime.now(timezone.utc)
    adv = snake(adversary) or "adversary"
    grp = snake(group) or "all"
    stamp = when.strftime("%Y%m%d-%H%M")
    return f"op_{adv}_{grp}_{stamp}"


def deduplicate(name: str, existing_names) -> str:
    """Append ``_2``, ``_3``, ... until the name is unique among existing_names."""
    existing = set(existing_names or ())
    if name not in existing:
        return name
    i = 2
    while f"{name}_{i}" in existing:
        i += 1
    return f"{name}_{i}"
