from __future__ import annotations
"""DOCX extractor - parses .docx into TranslationUnits."""

import re
from pathlib import Path
from typing import Optional

from docx import Document
from docx.document import Document as DocumentType
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from ..core import TranslationUnit, UnitPart
from ..core.config import log


class DocxExtractor:
    """Extracts translatable units from a .docx file."""

    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        if not self.filepath.exists():
            raise FileNotFoundError(f"Document not found: {self.filepath}")
        if self.filepath.suffix.lower() != ".docx":
            raise ValueError(f"Only .docx supported, got: {self.filepath.suffix}")

        self.doc: DocumentType = Document(str(self.filepath))
        self.units: list[TranslationUnit] = []
        self._counter = 0

    def extract(self) -> list[TranslationUnit]:
        """Extract all translatable units from the document."""
        self.units = []
        self._counter = 0

        log.info(f"Extracting from: {self.filepath.name}")
        log.info(f"  Paragraphs: {len(self.doc.paragraphs)}")
        log.info(f"  Tables: {len(self.doc.tables)}")

        # Extract headers
        for s_idx, section in enumerate(self.doc.sections):
            header = section.header
            if header:
                for p_idx, para in enumerate(header.paragraphs):
                    if para.text.strip():
                        self.units.append(self._make_unit(
                            part=UnitPart.HEADER,
                            path=f"header[s{s_idx}]/p[{p_idx}]",
                            text=para.text,
                            style_name=para.style.name if para.style else None,
                        ))

        # Extract body paragraphs
        for idx, para in enumerate(self.doc.paragraphs):
            if para.text.strip():
                unit = self._make_unit(
                    part=UnitPart.BODY,
                    path=f"body/p[{idx}]",
                    text=para.text,
                    style_name=para.style.name if para.style else None,
                )
                self.units.append(unit)

        # Extract table cells
        for t_idx, table in enumerate(self.doc.tables):
            for r_idx, row in enumerate(table.rows):
                for c_idx, cell in enumerate(row.cells):
                    if cell.text.strip():
                        unit = self._make_unit(
                            part=UnitPart.TABLE,
                            path=f"table[{t_idx}]/cell[{r_idx},{c_idx}]",
                            text=cell.text,
                            style_name=None,
                        )
                        self.units.append(unit)

        # Extract footers
        for s_idx, section in enumerate(self.doc.sections):
            footer = section.footer
            if footer:
                for p_idx, para in enumerate(footer.paragraphs):
                    if para.text.strip():
                        self.units.append(self._make_unit(
                            part=UnitPart.FOOTER,
                            path=f"footer[s{s_idx}]/p[{p_idx}]",
                            text=para.text,
                            style_name=para.style.name if para.style else None,
                        ))

        # Add context (preceding/following unit)
        for i, unit in enumerate(self.units):
            if i > 0:
                unit.context_before = self.units[i - 1].source_text[:200]
            if i < len(self.units) - 1:
                unit.context_after = self.units[i + 1].source_text[:200]

        log.info(f"Extracted {len(self.units)} translatable units")
        return self.units

    def _make_unit(
        self,
        part: UnitPart,
        path: str,
        text: str,
        style_name: Optional[str],
    ) -> TranslationUnit:
        self._counter += 1
        return TranslationUnit(
            unit_id=f"u{self._counter:04d}",
            part=part.value,
            path=path,
            source_text=text,
            style_name=style_name,
        )

    def get_structure_stats(self) -> dict:
        """Get document structure statistics for QA."""
        return {
            "paragraphs": sum(
                1 for u in self.units if u.part == UnitPart.BODY.value
            ),
            "table_cells": sum(
                1 for u in self.units if u.part == UnitPart.TABLE.value
            ),
            "headings": sum(
                1 for u in self.units if u.is_heading
            ),
            "total_units": len(self.units),
            "tables": len(self.doc.tables),
            "has_images": bool(
                self.doc.inline_shapes
            ),
        }
