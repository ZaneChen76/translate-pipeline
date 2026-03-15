from __future__ import annotations
"""QA report generation."""

from datetime import datetime
from pathlib import Path

from ..core import Task, QaIssue
from ..core.config import log


def generate_report(task: Task, output_path: str) -> str:
    """Generate a Markdown QA report for a completed task."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    errors = [i for i in task.issues if i.severity == "error"]
    warnings = [i for i in task.issues if i.severity == "warning"]
    infos = [i for i in task.issues if i.severity == "info"]

    with open(output, "w") as f:
        f.write(f"# QA Report: {task.source_file_name}\n\n")
        f.write(f"**Task ID**: {task.task_id}\n")
        f.write(f"**Generated**: {datetime.now().isoformat()}\n")
        f.write(f"**Status**: {task.status.value}\n\n")

        # Summary
        f.write("## Summary\n\n")
        f.write(f"| Metric | Value |\n|--------|-------|\n")
        f.write(f"| Total Units | {len(task.units)} |\n")
        f.write(f"| Translated | {sum(1 for u in task.units if u.translated_text and not u.error)} |\n")
        f.write(f"| Errors (QA) | {len(errors)} |\n")
        f.write(f"| Warnings (QA) | {len(warnings)} |\n")
        f.write(f"| TM Hits | {sum(1 for u in task.units if u.tm_hit)} |\n")

        if task.stats:
            f.write(f"\n**Source Stats**: {task.stats.get('source', {})}\n")

        # Errors
        if errors:
            f.write(f"\n## ❌ Errors ({len(errors)})\n\n")
            for issue in errors:
                f.write(f"### [{issue.category}] Unit {issue.unit_id or 'N/A'}\n\n")
                f.write(f"{issue.detail}\n\n")
                if issue.source_snippet:
                    f.write(f"**Source**: {issue.source_snippet}\n\n")
                if issue.target_snippet:
                    f.write(f"**Target**: {issue.target_snippet}\n\n")

        # Warnings
        if warnings:
            f.write(f"\n## ⚠️ Warnings ({len(warnings)})\n\n")
            for issue in warnings:
                f.write(f"### [{issue.category}] Unit {issue.unit_id or 'N/A'}\n\n")
                f.write(f"{issue.detail}\n\n")
                if issue.source_snippet:
                    f.write(f"**Source**: {issue.source_snippet}\n\n")
                if issue.target_snippet:
                    f.write(f"**Target**: {issue.target_snippet}\n\n")

        # Translation samples
        f.write("\n## Translation Samples\n\n")
        samples = [u for u in task.units if u.translated_text and not u.error][:10]
        for u in samples:
            f.write(f"### {u.unit_id} ({u.part})\n\n")
            f.write(f"**Source**:\n```\n{u.source_text[:300]}\n```\n\n")
            f.write(f"**Target**:\n```\n{(u.translated_text or '')[:500]}\n```\n\n")
            if u.tm_hit:
                f.write("*TM exact match*\n\n")
            f.write("---\n\n")

    log.info(f"QA report written to: {output.name}")
    return str(output)
