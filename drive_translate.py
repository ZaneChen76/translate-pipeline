#!/usr/bin/env python3
"""Drive-Driven Translation Pipeline

Usage:
  # Process next file from Drive inbox
  python3 drive_translate.py

  # Process a specific Drive file by ID
  python3 drive_translate.py --drive-file-id <id> --drive-file-name <name>

  # List Drive inbox without processing
  python3 drive_translate.py --list-only

Environment:
  HUNYUAN_API_KEY    — Hunyuan Lite API key
  GDRIVE_IN_FOLDER   — Drive translate/in folder ID
  GDRIVE_OUT_FOLDER  — Drive translate/out folder ID
"""
from __future__ import annotations

import os
import sys
import json
import time
from pathlib import Path

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.config import Config, log
from app.connectors.drive import DriveConnector, DriveFile
from app.worker.pipeline import Pipeline


def translate_from_drive(
    drive_file: DriveFile,
    local_input: str,
    pipeline: Pipeline,
    connector: DriveConnector,
) -> dict:
    """Run translation pipeline on a Drive file and upload result."""
    
    stem = Path(local_input).stem
    local_output = f"data/output/{stem}.en.docx"
    qa_report = f"data/output/{stem}.qa.md"
    
    start = time.time()
    
    # Run pipeline
    task = pipeline.run(
        input_path=local_input,
        output_path=local_output,
        qa_report_path=qa_report,
        resume=True,
    )
    
    elapsed = time.time() - start
    
    if task.output_file_path and Path(task.output_file_path).exists():
        # Upload to Drive out/
        result_name = f"{stem}.en.docx"
        uploaded = connector.upload_to_out(task.output_file_path, name=result_name)
        
        status_record = {
            "status": "success",
            "output": result_name,
            "drive_link": uploaded.link if uploaded else "",
            "units": len(task.units),
            "errors": sum(1 for i in task.issues if i.severity == "error"),
            "warnings": sum(1 for i in task.issues if i.severity == "warning"),
            "cjk_residue": sum(1 for i in task.issues if i.category == "cjk_residue"),
            "tm_hits": task.stats.get("tm_hits", 0),
            "elapsed_seconds": round(elapsed, 1),
            "translated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        
        # Update status.json in Drive in/
        connector.mark_processed(drive_file.name, status_record)
        
        return {"source": drive_file.name, **status_record}
    
    failed = {
        "status": "failed",
        "error": task.error or "Unknown error",
        "elapsed_seconds": round(elapsed, 1),
        "translated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    connector.mark_processed(drive_file.name, failed)
    return {"source": drive_file.name, **failed}


def format_summary(result: dict) -> str:
    """Format a human-readable conclusion summary."""
    if result.get("status") == "failed":
        return (
            f"❌ 翻译失败\n"
            f"📄 文件: {result['source']}\n"
            f"⚠️ 错误: {result.get('error', '未知错误')}\n"
            f"⏱ 耗时: {result.get('elapsed_seconds', '?')}s"
        )
    
    units = result.get("units", 0)
    errors = result.get("errors", 0)
    warnings = result.get("warnings", 0)
    cjk = result.get("cjk_residue", 0)
    tm = result.get("tm_hits", 0)
    elapsed = result.get("elapsed_seconds", 0)
    
    # Conclusion
    if errors == 0 and cjk == 0:
        conclusion = "✅ 翻译完成，质量合格"
    elif errors == 0 and cjk > 0:
        conclusion = f"⚠️ 翻译完成，{cjk} 处中文残留待修复"
    else:
        conclusion = f"⚠️ 翻译完成，{errors} 项 QA 错误需关注"
    
    # Time formatting
    if elapsed >= 60:
        time_str = f"{elapsed / 60:.0f}分{elapsed % 60:.0f}秒"
    else:
        time_str = f"{elapsed}s"
    
    return (
        f"{conclusion}\n"
        f"📄 {result['source']} → {result.get('output', '?')}\n"
        f"📊 {units} 单元 | {errors} 错误 | {warnings} 警告 | TM 命中 {tm}\n"
        f"⏱ 耗时: {time_str}\n"
        f"📁 输出: translate/out/{result.get('output', '?')}"
    )


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Drive-driven translation pipeline")
    ap.add_argument("--list-only", action="store_true", help="List Drive inbox only")
    ap.add_argument("--drive-file-id", help="Specific Drive file ID to process")
    ap.add_argument("--drive-file-name", help="Drive file name (with --drive-file-id)")
    ap.add_argument("--no-glossary", action="store_true")
    ap.add_argument("--no-qa", action="store_true")
    args = ap.parse_args()
    
    config = Config()
    if args.no_qa:
        config.qa_enabled = False
    
    connector = DriveConnector()
    pipeline = Pipeline(config)
    
    # List mode
    if args.list_only:
        files = connector.list_inbox()
        if not files:
            print("📭 Drive translate/in is empty")
        else:
            print(f"📂 Drive translate/in: {len(files)} files")
            for f in files:
                size_str = f"{f.size / 1024 / 1024:.1f}MB" if f.size else "unknown size"
                print(f"  📄 {f.name} ({size_str}) [{f.id}]")
        return
    
    # Process specific file
    if args.drive_file_id:
        drive_file = DriveFile(
            id=args.drive_file_id,
            name=args.drive_file_name or "document.docx",
        )
        local_path = connector.download(drive_file)
        if not local_path:
            print(f"❌ Failed to download {drive_file.name}")
            sys.exit(1)
    else:
        # Process next file from inbox
        result = connector.get_next_untranslated()
        if not result:
            print("📭 No DOCX files in Drive translate/in")
            return
        drive_file, local_path = result
    
    # Translate
    print(f"🔄 Translating: {drive_file.name}")
    result = translate_from_drive(drive_file, local_path, pipeline, connector)
    
    # Output JSON (machine-readable) and summary (human-readable)
    print()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print()
    print("─── 结论 ───")
    print(format_summary(result))
    
    if result["status"] != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
