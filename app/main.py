from __future__ import annotations
"""CLI entry point for TranslatePipeline."""

import argparse
import sys
from pathlib import Path

from .core.config import Config, setup_logging, log
from .qa.dashboard import generate_quality_dashboard
from .qa.dashboard_image import render_dashboard_image
from .worker.pipeline import Pipeline


def cmd_translate(args):
    """Execute translation pipeline."""
    config = Config()
    if args.config:
        config = Config.from_yaml(args.config)

    if args.translator:
        config.translator = args.translator
    if args.api_key:
        config.hunyuan_api_key = args.api_key
    if args.no_qa:
        config.qa_enabled = False

    log.info(f"Input:  {args.input}")
    log.info(f"Output: {args.output}")
    log.info(f"Translator: {config.translator}")

    pipeline = Pipeline(config)
    task = pipeline.run(
        input_path=args.input,
        output_path=args.output,
        qa_report_path=args.qa_report or "",
        glossary_path=args.glossary or "",
        resume=not args.no_resume,
    )

    # Print summary
    print(f"\n{'='*60}")
    print(f"  {task.summary()}")
    print(f"{'='*60}")

    if task.output_file_path:
        print(f"  Output:    {task.output_file_path}")
    if task.qa_report_path:
        print(f"  QA Report: {task.qa_report_path}")
    if task.stats:
        print(f"  Time:      {task.stats.get('elapsed_seconds', '?')}s")
        print(f"  Translator:{task.stats.get('translator', '?')}")
        print(f"  TM Hits:   {task.stats.get('tm_hits', 0)}")
        print(f"  Errors:    {task.stats.get('errors', 0)}")

    if task.status.value == "failed":
        print(f"\n  ❌ FAILED: {task.error}")
        return 1

    errors = sum(1 for i in task.issues if i.severity == "error")
    if errors:
        print(f"\n  ⚠️  Completed with {errors} QA errors — check report")
    else:
        print(f"\n  ✅ Completed successfully")

    return 0


def cmd_quality_report(args):
    source_path = args.source
    targets = args.targets or []
    report_path = args.report or ""

    report_or_text, metrics = generate_quality_dashboard(
        source_path=source_path,
        target_patterns=targets,
        output_dir=args.output_dir,
        report_path=report_path,
        glossary_path=args.glossary or "",
    )

    if report_path:
        print(f"Dashboard Report: {report_or_text}")
    else:
        print(report_or_text)

    if metrics:
        winner = sorted(metrics, key=lambda m: m.overall, reverse=True)[0]
        print(
            f"Best Candidate: {winner.name} | overall={winner.overall:.2f} | "
            f"accuracy={winner.accuracy:.2f} | structure={winner.structure_fidelity:.2f}"
        )

    if args.image:
        image_path = render_dashboard_image(source_path, metrics, args.image)
        print(f"Dashboard Image: {image_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="translate_pipeline",
        description="TranslateDocs - 技术文档/标书中译英保真翻译系统",
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # translate command
    p_trans = subparsers.add_parser("translate", help="Translate a document")
    p_trans.add_argument("--input", "-i", required=True, help="Input .docx file")
    p_trans.add_argument("--output", "-o", required=True, help="Output .docx file")
    p_trans.add_argument("--qa-report", "-q", help="QA report output path (.md)")
    p_trans.add_argument("--glossary", "-g", help="Glossary YAML file")
    p_trans.add_argument("--translator", "-t", choices=["mock", "hunyuan"], help="Translator to use")
    p_trans.add_argument("--api-key", help="Hunyuan API key (or set HUNYUAN_API_KEY env)")
    p_trans.add_argument("--config", "-c", help="Config YAML file")
    p_trans.add_argument("--no-qa", action="store_true", help="Skip QA checks")
    p_trans.add_argument("--no-resume", action="store_true", help="Disable checkpoint resume (start fresh)")
    p_trans.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    p_quality = subparsers.add_parser(
        "quality-report",
        help="Generate visual quality dashboard for one source and one/multiple targets",
    )
    p_quality.add_argument("--source", "-s", required=True, help="Source .docx path")
    p_quality.add_argument(
        "--targets",
        "-t",
        nargs="*",
        help="Target .docx paths or glob patterns (e.g. data/output/tdra03.en.*.docx)",
    )
    p_quality.add_argument(
        "--output-dir",
        default="data/output",
        help="Output directory for auto target discovery when --targets is omitted",
    )
    p_quality.add_argument("--glossary", "-g", help="Glossary YAML file")
    p_quality.add_argument("--report", "-r", help="Write dashboard to markdown file")
    p_quality.add_argument("--image", help="Write dashboard to PNG image")
    p_quality.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if getattr(args, "verbose", False):
        setup_logging(verbose=True)

    if args.command == "translate":
        return cmd_translate(args)
    if args.command == "quality-report":
        return cmd_quality_report(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
