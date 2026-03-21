from __future__ import annotations
"""Translation Memory (TM) - fuzzy matching with threshold."""

import json
import difflib
from pathlib import Path
from typing import Optional

from ..core import TmEntry
from ..core.config import log


class TranslationMemory:
    """File-based TM with fuzzy matching (rapidfuzz or difflib)."""

    def __init__(self, tm_dir, similarity_threshold: float = 0.85):
        self.tm_dir = Path(tm_dir)
        self.tm_dir.mkdir(parents=True, exist_ok=True)
        self.entries: list[TmEntry] = []
        self._index: dict[str, TmEntry] = {}  # source_text -> entry
        self.similarity_threshold = similarity_threshold
        try:
            from rapidfuzz import fuzz as _rf_fuzz
            self._rf = _rf_fuzz
        except Exception:
            self._rf = None

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
    def lookup(self, source_text: str):
        """Fuzzy lookup. Returns (entry, similarity, match_type) or None."""
        # Exact first
        entry = self._index.get(source_text)
        if entry:
            entry.hit_count += 1
            return entry, 1.0, "exact"
        # Fuzzy across all entries
        best = None
        best_sim = 0.0
        for e in self.entries:
            s1 = source_text.strip()
            s2 = e.source_text.strip()
            if not s1 or not s2:
                continue
            if self._rf is not None:
                sim = self._rf.token_set_ratio(s1, s2) / 100.0
                mtype = "rapidfuzz_token_set"
            else:
                sim = difflib.SequenceMatcher(None, s1, s2).ratio()
                mtype = "difflib_ratio"
            if sim > best_sim:
                best_sim = sim
                best = (e, sim, mtype)
        if best and best_sim >= self.similarity_threshold:
            best[0].hit_count += 1
            return best
        return None
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
