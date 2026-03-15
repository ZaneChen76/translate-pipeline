from __future__ import annotations
"""DOCX writer - writes translated text back into the document structure."""

import re
import shutil
from pathlib import Path

from docx import Document

from ..core import TranslationUnit, UnitPart
from ..core.config import log

# Path patterns matching extractor.py
_HEADER_RE = re.compile(r"^header\[s(\d+)\]/p\[(\d+)\]$")
_FOOTER_RE = re.compile(r"^footer\[s(\d+)\]/p\[(\d+)\]$")
_BODY_RE = re.compile(r"^body/p\[(\d+)\]$")
_TABLE_RE = re.compile(r"^table\[(\d+)\]/cell\[(\d+),(\d+)\]$")


class DocxWriter:
    """Writes translated units back into a DOCX file, preserving structure."""

    def __init__(self, source_path: str, units: list[TranslationUnit]):
        self.source_path = Path(source_path)
        self.units = units

    def write(self, output_path: str) -> str:
        """Write translated content to a new DOCX file.
        Returns the output file path.

        Uses path-based mapping (not position counting) to avoid misalignment
        when the document contains empty paragraphs or structural gaps.
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        # Copy source to preserve all structure/images/styles
        shutil.copy2(self.source_path, output)

        # Open the copy and replace text
        doc = Document(str(output))

        written = 0
        skipped = 0

        for unit in self.units:
            if not unit.translated_text or unit.error:
                continue

            m = _BODY_RE.match(unit.path)
            if m:
                idx = int(m.group(1))
                if idx < len(doc.paragraphs):
                    self._replace_paragraph_text(doc.paragraphs[idx], unit.translated_text)
                    written += 1
                else:
                    log.warning(f"Paragraph index {idx} out of range (path={unit.path})")
                    skipped += 1
                continue

            m = _HEADER_RE.match(unit.path)
            if m:
                s_idx, p_idx = int(m.group(1)), int(m.group(2))
                if s_idx < len(doc.sections):
                    paras = doc.sections[s_idx].header.paragraphs
                    if p_idx < len(paras):
                        self._replace_paragraph_text(paras[p_idx], unit.translated_text)
                        written += 1
                    else:
                        log.warning(f"Header para index {p_idx} out of range (path={unit.path})")
                        skipped += 1
                else:
                    log.warning(f"Section index {s_idx} out of range (path={unit.path})")
                    skipped += 1
                continue

            m = _FOOTER_RE.match(unit.path)
            if m:
                s_idx, p_idx = int(m.group(1)), int(m.group(2))
                if s_idx < len(doc.sections):
                    paras = doc.sections[s_idx].footer.paragraphs
                    if p_idx < len(paras):
                        self._replace_paragraph_text(paras[p_idx], unit.translated_text)
                        written += 1
                    else:
                        log.warning(f"Footer para index {p_idx} out of range (path={unit.path})")
                        skipped += 1
                else:
                    log.warning(f"Section index {s_idx} out of range (path={unit.path})")
                    skipped += 1
                continue

            m = _TABLE_RE.match(unit.path)
            if m:
                t_idx, r_idx, c_idx = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if t_idx < len(doc.tables):
                    table = doc.tables[t_idx]
                    if r_idx < len(table.rows) and c_idx < len(table.rows[r_idx].cells):
                        self._replace_cell_text(table.rows[r_idx].cells[c_idx], unit.translated_text)
                        written += 1
                    else:
                        log.warning(f"Table cell index [{r_idx},{c_idx}] out of range (path={unit.path})")
                        skipped += 1
                else:
                    log.warning(f"Table index {t_idx} out of range (path={unit.path})")
                    skipped += 1
                continue

            log.warning(f"Unrecognized path format: {unit.path}")
            skipped += 1

        doc.save(str(output))
        log.info(f"Written output to: {output.name} ({written} units written, {skipped} skipped)")
        return str(output)

    def _replace_paragraph_text(self, para, new_text: str):
        """Replace paragraph text, preserving the first run's formatting (font, size, bold, etc.).

        Per-word formatting is necessarily lost since translated text has different
        word boundaries than the source. This is an acceptable tradeoff for translation.
        """
        if not para.runs:
            para.text = new_text
            return

        # Keep first run (preserves <w:rPr> formatting), replace its text
        first_run = para.runs[0]
        first_run.text = new_text

        # Remove remaining runs from XML (not just clear text — removes the run elements)
        for run in para.runs[1:]:
            run._element.getparent().remove(run._element)

    def _replace_cell_text(self, cell, new_text: str):
        """Replace table cell text, preserving first run's formatting."""
        for para in cell.paragraphs:
            if para.runs:
                first_run = para.runs[0]
                first_run.text = new_text
                for run in para.runs[1:]:
                    run._element.getparent().remove(run._element)
                return
        if cell.paragraphs:
            cell.paragraphs[0].text = new_text
