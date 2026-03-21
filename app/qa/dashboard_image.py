from __future__ import annotations
"""Render quality dashboard PNG with context-doctor style pipeline (ANSI -> SVG -> PNG)."""

import os
import subprocess
from pathlib import Path
import io
import textwrap
from typing import Callable, List

from rich.console import Console as RichConsole
from rich.text import Text as RichText

from .dashboard import QualityMetrics

# ANSI palette aligned with context-doctor style
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"
GRAY = "\033[90m"
BRIGHT_GREEN = "\033[92m"
BRIGHT_YELLOW = "\033[93m"
BRIGHT_CYAN = "\033[96m"
BRIGHT_WHITE = "\033[97m"


def _c(color_code: str, text: str) -> str:
    rendered = str(text).replace(RESET, f"{RESET}{color_code}")
    return f"{color_code}{rendered}{RESET}"


def _status_color(score: float) -> str:
    if score >= 85:
        return BRIGHT_GREEN
    if score >= 70:
        return BRIGHT_YELLOW
    return RED


def _mask_prefix(text: str) -> str:
    return "".join("▓" if ch not in "._-" else ch for ch in text)


def _mask_filename(name: str) -> str:
    if ".en." in name:
        left, right = name.split(".en.", 1)
        return "{0}.en.{1}".format(_mask_prefix(left), right)
    if "." in name:
        stem, ext = name.rsplit(".", 1)
        return "{0}.{1}".format(_mask_prefix(stem), ext)
    return _mask_prefix(name)


def _trim(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def _pad(text: str, width: int, align: str = "left") -> str:
    if len(text) >= width:
        return text[:width]
    if align == "right":
        return " " * (width - len(text)) + text
    return text + " " * (width - len(text))


def _bar(value: float, width: int = 36, color: str = GREEN) -> str:
    v = max(0.0, min(100.0, value))
    filled = int(round(v / 100.0 * width))
    empty = width - filled
    return _c(color, "█" * filled) + _c(GRAY, "░" * empty)


def _append_glossary_line(lines: List[str], label: str, desc: str, total_width: int, label_width: int = 14) -> None:
    line_prefix_width = 2 + label_width + 1
    desc_width = max(20, total_width - line_prefix_width)
    wrapped = textwrap.wrap(desc, width=desc_width, break_long_words=False, break_on_hyphens=False) or [""]
    lines.append(f"  {_c(DIM, _pad(label, label_width))} {_c(WHITE, wrapped[0])}")
    for cont in wrapped[1:]:
        lines.append(f"  {_c(DIM, ' ' * label_width)} {_c(WHITE, cont)}")


def _build_report_text(source_path: str, metrics_list: List[QualityMetrics]) -> str:
    ranked = sorted(metrics_list, key=lambda m: m.overall, reverse=True)
    width = 86

    lines = []
    lines.append(f"  {_c(BOLD + BRIGHT_CYAN, '● TranslateDocs Quality Window Breakdown')}  {_c(DIM, '(2026.3.21)')}")
    lines.append(f"  {_c(GRAY, '━' * width)}")
    lines.append("")
    source_label = _c(DIM, _pad("Source", 12))
    compared_label = _c(DIM, _pad("Compared", 12))
    lines.append(
        f"  {source_label} {_c(WHITE, _mask_filename(Path(source_path).name))}\n"
        f"  {compared_label} {_c(WHITE, str(len(ranked)) + ' candidates')}"
    )

    lines.append("")
    lines.append(f"  {_c(BOLD + BRIGHT_CYAN, '▣ Ranking')}")
    lines.append(f"  {_c(GRAY, '─' * width)}")
    lines.append("")
    for idx, m in enumerate(ranked, 1):
        name = _trim(_mask_filename(m.name), 40)
        color = _status_color(m.overall)
        idx_part = _c(BRIGHT_WHITE, _pad(str(idx), 2, "right"))
        name_part = _c(WHITE, _pad(name, 42))
        val_part = _c(BRIGHT_CYAN, _pad(f"{m.overall:6.2f}", 6, "right"))
        lines.append(
            f"  {idx_part}  {name_part}  {_bar(m.overall, 24, color)}  {val_part}"
        )

    lines.append("")
    lines.append(f"  {_c(BOLD + BRIGHT_CYAN, '▣ Detail Breakdown')}")
    lines.append(f"  {_c(GRAY, '─' * width)}")
    lines.append("")

    metric_rows: List[tuple[str, Callable[[QualityMetrics], float]]] = [
        ("Accuracy", lambda x: x.accuracy),
        ("Completeness", lambda x: x.completeness),
        ("Structure", lambda x: x.structure_fidelity),
        ("Professional", lambda x: x.professionalism),
        ("Terminology", lambda x: x.terminology_consistency),
        ("Scope", lambda x: x.scope_adherence),
    ]

    for m in ranked:
        lines.append(f"  {_c(GRAY, '┌' + '─' * (width - 2) + '┐')}")
        title = _trim(_mask_filename(m.name), 46)
        header_left = _c(BRIGHT_WHITE, _pad(title, 48))
        header_right = _c(BRIGHT_CYAN, _pad(f"overall {m.overall:6.2f}", 16, "right"))
        lines.append(f"  {_c(GRAY, '│')} {header_left}  {header_right}")
        lines.append(f"  {_c(GRAY, '│')}")

        for label, getter in metric_rows:
            val = getter(m)
            color = _status_color(val)
            label_part = _c(DIM, _pad(label, 12))
            val_part = _c(BRIGHT_WHITE, _pad(f"{val:6.2f}", 6, "right"))
            lines.append(f"  {_c(GRAY, '│')} {label_part}  {_bar(val, 30, color)}  {val_part}")

        unit_line = "units {0}/{1}/{2} | number {3:.2f} | cjk {4:.2f}%".format(
            m.aligned_units, m.nonempty_units, m.total_units, m.number_integrity, m.cjk_residue_ratio
        )
        alerts_text = "alerts: " + (", ".join(m.findings[:2]) if m.findings else "none")
        lines.append(f"  {_c(GRAY, '│')} {_c(DIM, _trim(unit_line, 78))}")
        lines.append(f"  {_c(GRAY, '│')} {_c(DIM, _trim(alerts_text, 78))}")
        lines.append(f"  {_c(GRAY, '└' + '─' * (width - 2) + '┘')}")
        lines.append("")

    lines.append(f"  {_c(BOLD + BRIGHT_CYAN, '▣ Metrics Glossary')}")
    lines.append(f"  {_c(GRAY, '─' * width)}")
    lines.append("")
    _append_glossary_line(lines, "Accuracy", "0.38*N + 0.32*T + 0.12*Scope + 0.18*(100-CJK_penalty)", width)
    _append_glossary_line(lines, "Completeness", "100 * (0.7*aligned_ratio + 0.3*nonempty_ratio)", width)
    _append_glossary_line(lines, "Structure", "50% struct checks(paragraph/table/cell) + 50% path alignment", width)
    _append_glossary_line(lines, "Professional", "100 - min(35, forbidden_hits*6) - CJK_penalty", width)
    _append_glossary_line(lines, "Terminology", "rep_consistency; with glossary: 0.55*rep + 0.45*glossary_hit", width)
    _append_glossary_line(lines, "Scope", "length-ratio tiers, then minus min(30, forbidden_hits*4)", width)
    _append_glossary_line(lines, "Overall", "0.27*A + 0.18*C + 0.20*S + 0.13*P + 0.12*T + 0.10*Scope", width)
    lines.append("")
    _append_glossary_line(lines, "N", "number_integrity: source numbers preserved in target (100 = all matched)", width)
    _append_glossary_line(lines, "T", "terminology_consistency: repetition consistency, blended with glossary hit ratio", width)
    _append_glossary_line(lines, "CJK_penalty", "min(35, cjk_ratio*100*0.45), where cjk_ratio = cjk_units/aligned_units", width)
    _append_glossary_line(lines, "A/C/S/P", "A=Accuracy, C=Completeness, S=Structure, P=Professionalism", width)
    lines.append("")
    lines.append(f"  {_c(DIM, 'translate-pipeline • terminal-style renderer')}")
    lines.append("")
    return "\n".join(lines)


def render_dashboard_image(source_path: str, metrics_list: List[QualityMetrics], output_path: str) -> str:
    text = _build_report_text(source_path, metrics_list)

    out = Path(output_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    svg_path = out.with_suffix(".svg")

    console = RichConsole(record=True, width=92, force_terminal=True, file=io.StringIO())
    console.print(RichText.from_ansi(text))
    svg = console.export_svg(title="QA Quality Comparison")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(svg)

    try:
        subprocess.run(
            ["/opt/homebrew/bin/rsvg-convert", str(svg_path), "-o", str(out), "-z", "2"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"PNG convert failed: {e.stderr or e.stdout}") from e

    try:
        os.remove(svg_path)
    except OSError:
        pass
    return str(out)
