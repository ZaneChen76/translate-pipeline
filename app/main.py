from __future__ import annotations
"""CLI entry point for TranslatePipeline."""

import argparse
import sys
from pathlib import Path

from .core.config import Config, setup_logging, log
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

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if getattr(args, "verbose", False):
        setup_logging(verbose=True)

    if args.command == "translate":
        return cmd_translate(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
