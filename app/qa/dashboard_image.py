from __future__ import annotations
"""PNG renderer for translation quality dashboard."""

from pathlib import Path
from typing import List

from PIL import Image, ImageDraw, ImageFont

from .dashboard import QualityMetrics


def _load_font(size: int):
    candidates = [
        "/System/Library/Fonts/Supplemental/Andale Mono.ttf",
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/System/Library/Fonts/Supplemental/Menlo.ttc",
        "/System/Library/Fonts/Supplemental/SFNSMono.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _load_title_font(size: int):
    candidates = [
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return _load_font(size)


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


def _draw_dots(draw, x, y, w, h, color="#525252", step=6):
    for px in range(x + 2, x + w - 1, step):
        for py in range(y + 2, y + h - 1, step):
            draw.point((px, py), fill=color)


def _fit_text(draw, text, font, max_width):
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "..."
    trimmed = text
    while trimmed and draw.textlength(trimmed + suffix, font=font) > max_width:
        trimmed = trimmed[:-1]
    return trimmed + suffix


def _bar(draw, x, y, w, h, score, fill="#a6bd55", back="#2f3237", dots="#7a7e86"):
    score = max(0.0, min(100.0, float(score)))
    draw.rectangle((x, y, x + w, y + h), fill=back, outline="#686c74", width=1)
    _draw_dots(draw, x, y, w, h, color=dots, step=5)
    for i in range(0, 6):
        tx = x + int(w * i / 5.0)
        draw.line((tx, y + 1, tx, y + h - 1), fill="#5b5f67", width=1)
    fw = int(w * score / 100.0)
    if fw > 0:
        draw.rectangle((x + 1, y + 1, x + fw, y + h - 1), fill=fill)


def _draw_metric_legend(draw, x, y, w, fonts, fg, muted, accent, line):
    text_font, small_font, tiny_font = fonts
    draw.text((x, y), "▶ Metrics Glossary", font=text_font, fill=accent)
    y += 34
    draw.line((x, y, x + w, y), fill=line, width=1)
    y += 14

    legends = [
        ("Accuracy", "number integrity + terminology consistency + scope adherence - cjk residue penalty"),
        ("Completeness", "aligned translatable units + non-empty target coverage"),
        ("Structure", "paragraph/table/cell parity + path-level alignment"),
        ("Professional", "penalty for chain-of-thought leakage, notes and language residue"),
        ("Terminology", "repeated-source stability + glossary hit ratio"),
        ("Scope", "length-ratio drift and unsupported expansion risk"),
        ("Overall", "weighted score (A27 C18 S20 P13 T12 Sc10)"),
    ]
    for k, v in legends:
        draw.text((x + 6, y), k, font=small_font, fill=fg)
        draw.text((x + 210, y), v, font=tiny_font, fill=muted)
        y += 22
    return y


def _status_color(score, ok, warn, bad):
    if score >= 85:
        return ok
    if score >= 70:
        return warn
    return bad


def _build_alerts(m: QualityMetrics) -> str:
    alerts = []
    if m.cjk_residue_ratio > 5:
        alerts.append("CJK residue")
    if m.number_integrity < 95:
        alerts.append("number drift")
    if m.scope_adherence < 70:
        alerts.append("scope drift")
    if m.professionalism < 70:
        alerts.append("style risk")
    if not m.paragraph_match or not m.cell_match or not m.table_match:
        alerts.append("structure risk")
    if not alerts:
        return "alerts: none"
    return "alerts: " + ", ".join(alerts[:3])


def render_dashboard_image(source_path: str, metrics_list: List[QualityMetrics], output_path: str) -> str:
    ranked = sorted(metrics_list, key=lambda m: m.overall, reverse=True)
    card_h = 208
    header_h = 250 + 40 * len(ranked)
    legend_h = 300
    footer_h = 58
    width = 1800
    height = header_h + card_h * len(ranked) + legend_h + footer_h

    bg = "#1e1f22"
    pane = "#232529"
    fg = "#d2d5d9"
    muted = "#9fa4aa"
    accent = "#2d8d8b"
    line = "#666a70"
    ok = "#9aae4b"
    warn = "#c9b35b"
    bad = "#b55c5c"
    cyan = "#77b6d4"

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    title_font = _load_title_font(44)
    h2_font = _load_font(30)
    text_font = _load_font(24)
    small_font = _load_font(20)
    tiny_font = _load_font(17)

    # Terminal-like main pane
    margin = 22
    draw.rectangle((margin, margin, width - margin, height - margin), fill=pane, outline="#4f5358", width=2)

    # Window header
    bar_top = margin + 10
    bar_h = 34
    draw.rectangle((margin + 2, bar_top, width - margin - 2, bar_top + bar_h), fill="#2c2f33")
    cx = margin + 20
    for color in ("#ff5f57", "#ffbd2e", "#28c840"):
        draw.ellipse((cx, bar_top + 8, cx + 16, bar_top + 24), fill=color)
        cx += 24
    draw.text((width // 2 - 140, bar_top + 5), "context-doctor", font=small_font, fill="#b8bec5")

    y = bar_top + bar_h + 18
    draw.text((margin + 20, y), "● Translation Quality Window Breakdown", font=h2_font, fill=accent)
    draw.text((margin + 760, y + 2), "(2026.3.20)", font=text_font, fill=muted)
    y += 52
    draw.line((margin + 18, y, width - margin - 18, y), fill=line, width=2)
    y += 22

    src_name = Path(source_path).name
    src_masked = _mask_filename(src_name)
    draw.text((margin + 18, y), "Source", font=text_font, fill=muted)
    draw.text((margin + 170, y), src_masked, font=text_font, fill=fg)
    y += 42
    draw.text((margin + 18, y), "Compared", font=text_font, fill=muted)
    draw.text((margin + 170, y), "{0} candidates".format(len(ranked)), font=text_font, fill=fg)
    y += 48

    draw.text((margin + 18, y), "▣ Ranking", font=h2_font, fill=accent)
    y += 46
    draw.line((margin + 18, y, width - margin - 18, y), fill=line, width=1)
    y += 14

    for i, m in enumerate(ranked, 1):
        masked_name = _mask_filename(m.name)
        draw.text((margin + 24, y), "{0:>2}".format(i), font=text_font, fill=fg)
        draw.text((margin + 74, y), _fit_text(draw, masked_name, text_font, 860), font=text_font, fill=fg)
        _bar(
            draw,
            margin + 980,
            y + 4,
            470,
            24,
            m.overall,
            fill=_status_color(m.overall, ok, warn, bad),
        )
        draw.text((margin + 1470, y), "{0:6.2f}".format(m.overall), font=text_font, fill=cyan)
        y += 38

    y += 18
    draw.text((margin + 18, y), "▤ Detail Breakdown", font=h2_font, fill=accent)
    y += 46
    draw.line((margin + 18, y, width - margin - 18, y), fill=line, width=1)
    y += 14

    for m in ranked:
        draw.rectangle((margin + 18, y, width - margin - 18, y + card_h - 22), outline=line, width=1)
        draw.text(
            (margin + 34, y + 10),
            _fit_text(draw, _mask_filename(m.name), text_font, 980),
            font=text_font,
            fill=fg,
        )
        draw.text(
            (width - margin - 360, y + 10),
            "overall {0:6.2f}".format(m.overall),
            font=text_font,
            fill=accent,
        )

        metrics = [
            ("Accuracy", m.accuracy),
            ("Completeness", m.completeness),
            ("Structure", m.structure_fidelity),
            ("Professional", m.professionalism),
            ("Terminology", m.terminology_consistency),
            ("Scope", m.scope_adherence)
        ]
        by = y + 54
        for label, score in metrics:
            draw.text((margin + 36, by), label, font=small_font, fill=muted)
            fill = _status_color(score, ok, warn, bad)
            _bar(draw, margin + 250, by + 3, 560, 18, score, fill=fill)
            draw.text((margin + 840, by), "{0:6.2f}".format(score), font=small_font, fill=fg)
            by += 25

        draw.text(
            (margin + 940, y + 56),
            "units {0}/{1}/{2}".format(m.aligned_units, m.nonempty_units, m.total_units),
            font=small_font,
            fill=muted,
        )
        draw.text(
            (margin + 940, y + 86),
            "number {0:.2f} | cjk {1:.2f}%".format(m.number_integrity, m.cjk_residue_ratio),
            font=small_font,
            fill=muted,
        )
        draw.text((margin + 940, y + 116), _build_alerts(m), font=small_font, fill="#d39d7a")
        draw.text(
            (margin + 940, y + 146),
            "structure: p={0} t={1} c={2}".format(
                "OK" if m.paragraph_match else "FAIL",
                "OK" if m.table_match else "FAIL",
                "OK" if m.cell_match else "FAIL",
            ),
            font=tiny_font,
            fill=muted,
        )
        y += card_h

    y += 10
    y = _draw_metric_legend(
        draw,
        margin + 18,
        y,
        width - (margin + 18) * 2,
        (text_font, small_font, tiny_font),
        fg,
        muted,
        accent,
        line,
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out), format="PNG")
    return str(out)
