from __future__ import annotations
"""Glossary management - term lookup and injection."""

import re
from pathlib import Path
from typing import Optional

import yaml

from ..core import GlossaryEntry
from ..core.config import log


class Glossary:
    """Manages project-specific terminology glossary."""

    def __init__(self):
        self.entries: list[GlossaryEntry] = []
        # Note: substring search in lookup_text requires scanning entries.
        # For exact-term lookup, use a direct dict: {entry.source_term: entry.target_term}

    def load_yaml(self, path):
        """Load glossary from YAML file."""
        path = Path(path)
        if not path.exists():
            log.warning(f"Glossary file not found: {path}")
            return

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        terms = data.get("terms", [])
        for t in terms:
            entry = GlossaryEntry(
                source_term=t["source"],
                target_term=t["target"],
                domain=t.get("domain"),
                notes=t.get("note"),
                case_sensitive=t.get("case_sensitive", False),
            )
            self.add_entry(entry)

        log.info(f"Loaded {len(terms)} glossary entries from {path.name}")

    def add_entry(self, entry: GlossaryEntry):
        """Add a glossary entry."""
        self.entries.append(entry)

    def lookup_text(self, text: str) -> dict[str, str]:
        """Find all glossary terms present in the given text.
        Returns dict of {source_term: target_term} for matches.
        Uses _lookup dict for O(1) substring checks instead of scanning all entries.
        """
        hits = {}
        text_lower = text.lower()
        for entry in self.entries:
            if not entry.active:
                continue
            src = entry.source_term
            if entry.case_sensitive:
                if src in text:
                    hits[src] = entry.target_term
            else:
                if src.lower() in text_lower:
                    hits[src] = entry.target_term
        return hits

    def format_for_prompt(self, hits: dict[str, str]) -> str:
        """Format glossary hits for inclusion in translation prompt."""
        if not hits:
            return ""
        lines = [f"- {src} → {tgt}" for src, tgt in hits.items()]
        return "\n".join(lines)

    @property
    def size(self) -> int:
        return len(self.entries)
