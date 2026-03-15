from __future__ import annotations
"""DOCX writer - writes translated text back into the document structure."""

import shutil
from pathlib import Path
from typing import Optional

from docx import Document
from docx.document import Document as DocumentType
from docx.table import Table

from ..core import TranslationUnit, UnitPart
from ..core.config import log


class DocxWriter:
    """Writes translated units back into a DOCX file, preserving structure."""

    def __init__(self, source_path: str, units: list[TranslationUnit]):
        self.source_path = Path(source_path)
        self.units = units
        self.unit_map = {u.unit_id: u for u in units}

    def write(self, output_path: str) -> str:
        """
        Write translated content to a new DOCX file.
        Returns the output file path.
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        # Copy source to preserve all structure/images/styles
        shutil.copy2(self.source_path, output)

        # Open the copy and replace text
        doc = Document(str(output))

        # Build path -> translation mapping
        body_units = [u for u in self.units if u.part == UnitPart.BODY.value]
        table_units = [u for u in self.units if u.part == UnitPart.TABLE.value]

        # Write body paragraphs
        body_idx = 0
        for idx, para in enumerate(doc.paragraphs):
            if para.text.strip():
                # Find matching unit by position
                if body_idx < len(body_units):
                    unit = body_units[body_idx]
                    if unit.translated_text and not unit.error:
                        self._replace_paragraph_text(para, unit.translated_text)
                    body_idx += 1

        # Write table cells
        table_cell_idx = 0
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        if table_cell_idx < len(table_units):
                            unit = table_units[table_cell_idx]
                            if unit.translated_text and not unit.error:
                                self._replace_cell_text(cell, unit.translated_text)
                            table_cell_idx += 1

        doc.save(str(output))
        log.info(f"Written output to: {output.name}")
        return str(output)

    def _replace_paragraph_text(self, para, new_text: str):
        """Replace paragraph text while trying to preserve run structure."""
        if not para.runs:
            para.text = new_text
            return

        # Strategy: clear all runs, put full text in first run, clear rest
        first_run = para.runs[0]
        first_run.text = new_text
        for run in para.runs[1:]:
            run.text = ""

    def _replace_cell_text(self, cell, new_text: str):
        """Replace table cell text."""
        for para in cell.paragraphs:
            if para.runs:
                para.runs[0].text = new_text
                for run in para.runs[1:]:
                    run.text = ""
                return
        # No runs, set paragraph text directly
        if cell.paragraphs:
            cell.paragraphs[0].text = new_text
