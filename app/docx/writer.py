from __future__ import annotations
"""DOCX writer - writes translated text back into the document structure."""

import re
import shutil
from pathlib import Path

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn

from ..core import TranslationUnit, UnitPart
from ..core.config import log

# Path patterns matching extractor.py
_HEADER_RE = re.compile(r"^header\[s(\d+)\]/p\[(\d+)\]$")
_FOOTER_RE = re.compile(r"^footer\[s(\d+)\]/p\[(\d+)\]$")
_BODY_RE = re.compile(r"^body/p\[(\d+)\]$")
_TABLE_RE = re.compile(r"^table\[(\d+)\]/cell\[(\d+),(\d+)\]$")
_TEXTBOX_RE = re.compile(r"^textbox\[(\d+)\]/p\[(\d+)\]$")
_FOOTNOTE_RE = re.compile(r"^footnote\[(\-?\d+)\]/p\[(\d+)\]$")
_ENDNOTE_RE = re.compile(r"^endnote\[(\-?\d+)\]/p\[(\d+)\]$")



def _replace_w_p_text(p_el, new_text: str):
    """Replace text inside a w:p element, preserving first run properties."""
    from lxml import etree
    nsmap = p_el.nsmap.copy()
    nsmap.setdefault('w', 'http://schemas.openxmlformats.org/wordprocessingml/2006/main')
    runs = p_el.xpath('./w:r', namespaces=nsmap)
    if not runs:
        r = etree.SubElement(p_el, qn('w:r'))
        t = etree.SubElement(r, qn('w:t'))
        t.text = new_text
        return
    t_nodes = runs[0].xpath('.//w:t', namespaces=nsmap)
    if t_nodes:
        t_nodes[0].text = new_text
    else:
        t = etree.SubElement(runs[0], qn('w:t'))
        t.text = new_text
    for r in runs[1:]:
        parent = r.getparent()
        if parent is not None:
            parent.remove(r)

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

            m = _TEXTBOX_RE.match(unit.path)
            if m:
                tbx_idx, p_idx = int(m.group(1)), int(m.group(2))
                try:
                    root = doc._element
                    nsmap = root.nsmap.copy()
                    nsmap.setdefault('w', 'http://schemas.openxmlformats.org/wordprocessingml/2006/main')
                    txbx_list = root.xpath('.//w:txbxContent', namespaces=nsmap)
                    if tbx_idx < len(txbx_list):
                        paras = txbx_list[tbx_idx].xpath('./w:p', namespaces=nsmap)
                        if p_idx < len(paras):
                            _replace_w_p_text(paras[p_idx], unit.translated_text)
                            written += 1
                        else:
                            log.warning(f"Textbox para index {p_idx} out of range (path={unit.path})")
                            skipped += 1
                    else:
                        log.warning(f"Textbox index {tbx_idx} out of range (path={unit.path})")
                        skipped += 1
                except Exception as e:
                    log.warning(f"Textbox write failed for {unit.path}: {e}")
                    skipped += 1
                continue

            m = _FOOTNOTE_RE.match(unit.path)
            if m:
                fid, p_idx = m.group(1), int(m.group(2))
                try:
                    part = next((rel.target_part for rel in doc.part.rels.values() if rel.reltype == RT.FOOTNOTES), None)
                    if part is not None:
                        el = part.element
                        nsmap = el.nsmap.copy()
                        nsmap.setdefault('w', 'http://schemas.openxmlformats.org/wordprocessingml/2006/main')
                        fns = el.xpath("./w:footnote[@w:id='" + str(fid) + "']", namespaces=nsmap)
                        if fns:
                            paras = fns[0].xpath('./w:p', namespaces=nsmap)
                            if p_idx < len(paras):
                                _replace_w_p_text(paras[p_idx], unit.translated_text)
                                written += 1
                            else:
                                log.warning(f"Footnote para index {p_idx} out of range (path={unit.path})")
                                skipped += 1
                        else:
                            log.warning(f"Footnote id {fid} not found (path={unit.path})")
                            skipped += 1
                    else:
                        log.warning('No footnotes part present')
                        skipped += 1
                except Exception as e:
                    log.warning(f"Footnote write failed for {unit.path}: {e}")
                    skipped += 1
                continue

            m = _ENDNOTE_RE.match(unit.path)
            if m:
                eid, p_idx = m.group(1), int(m.group(2))
                try:
                    part = next((rel.target_part for rel in doc.part.rels.values() if rel.reltype == RT.ENDNOTES), None)
                    if part is not None:
                        el = part.element
                        nsmap = el.nsmap.copy()
                        nsmap.setdefault('w', 'http://schemas.openxmlformats.org/wordprocessingml/2006/main')
                        ens = el.xpath("./w:endnote[@w:id='" + str(eid) + "']", namespaces=nsmap)
                        if ens:
                            paras = ens[0].xpath('./w:p', namespaces=nsmap)
                            if p_idx < len(paras):
                                _replace_w_p_text(paras[p_idx], unit.translated_text)
                                written += 1
                            else:
                                log.warning(f"Endnote para index {p_idx} out of range (path={unit.path})")
                                skipped += 1
                        else:
                            log.warning(f"Endnote id {eid} not found (path={unit.path})")
                            skipped += 1
                    else:
                        log.warning('No endnotes part present')
                        skipped += 1
                except Exception as e:
                    log.warning(f"Endnote write failed for {unit.path}: {e}")
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
        """Replace full table-cell text and clear residual content in extra paragraphs."""
        if not cell.paragraphs:
            return

        # Clear all paragraph text first to avoid leaving untranslated residue.
        for para in cell.paragraphs:
            if para.runs:
                para.runs[0].text = ""
                for run in para.runs[1:]:
                    run._element.getparent().remove(run._element)
            else:
                para.text = ""

        # Write translated text into the first paragraph (keeps structure intact).
        self._replace_paragraph_text(cell.paragraphs[0], new_text)
