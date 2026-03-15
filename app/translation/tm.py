from __future__ import annotations
"""Translation Memory (TM) - exact match reuse."""

import json
from pathlib import Path
from typing import Optional

from ..core import TmEntry
from ..core.config import log


class TranslationMemory:
    """Simple file-based translation memory with exact match."""

    def __init__(self, tm_dir):
        self.tm_dir = Path(tm_dir)
        self.tm_dir.mkdir(parents=True, exist_ok=True)
        self.entries: list[TmEntry] = []
        self._index: dict[str, TmEntry] = {}  # source_text -> entry

    def load(self, project_id: Optional[str] = None):
        """Load TM entries from JSON files."""
        pattern = f"{project_id}_tm.json" if project_id else "*_tm.json"
        for path in self.tm_dir.glob(pattern):
            try:
                with open(path) as f:
                    data = json.load(f)
                for item in data:
                    entry = TmEntry(**item)
                    self.entries.append(entry)
                    self._index[entry.source_text] = entry
                log.info(f"Loaded {len(data)} TM entries from {path.name}")
            except Exception as e:
                log.warning(f"Failed to load TM from {path}: {e}")

    def lookup(self, source_text: str) -> Optional[TmEntry]:
        """Exact match lookup. Returns TM entry if found."""
        entry = self._index.get(source_text)
        if entry:
            entry.hit_count += 1
        return entry

    def add(self, source: str, target: str, source_doc: str = "", confirmed: bool = False):
        """Add a new TM entry."""
        if source in self._index:
            return  # already exists
        entry = TmEntry(
            source_text=source,
            target_text=target,
            source_doc=source_doc,
            confirmed=confirmed,
        )
        self.entries.append(entry)
        self._index[source] = entry

    def save(self, project_id: str = "default"):
        """Save TM to disk."""
        path = self.tm_dir / f"{project_id}_tm.json"
        data = [
            {
                "source_text": e.source_text,
                "target_text": e.target_text,
                "source_doc": e.source_doc,
                "confirmed": e.confirmed,
                "hit_count": e.hit_count,
            }
            for e in self.entries
        ]
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        log.info(f"Saved {len(self.entries)} TM entries to {path.name}")

    @property
    def size(self) -> int:
        return len(self.entries)
