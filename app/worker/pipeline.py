from __future__ import annotations
"""Pipeline worker - orchestrates the full translation workflow."""

import json
import signal
import sys
import time
from pathlib import Path

from ..core import Task, TaskStatus, UnitPart, TranslationUnit
from ..core.config import Config, log
from ..docx.extractor import DocxExtractor
from ..docx.writer import DocxWriter
from ..translation.translator import Translator, create_translator
from ..translation.glossary import Glossary
from ..translation.tm import TranslationMemory
from ..qa.checks import StructureChecker, NumberChecker, TermChecker, MissingTranslationChecker, ChineseResidueChecker
from ..qa.report import generate_report

# Retry configuration
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0  # seconds
RETRY_BACKOFF_MAX = 30.0
CHECKPOINT_EVERY = 5  # save checkpoint every N units


class Pipeline:
    """Full translation pipeline: extract → translate → QA → write."""

    def __init__(self, config: Config):
        self.config = config
        self.translator: Translator | None = None
        self.glossary = Glossary()
        self.tm = TranslationMemory(config.tm_dir)
        self.structure_checker = StructureChecker()
        self.number_checker = NumberChecker()
        self.term_checker = TermChecker()
        self.missing_checker = MissingTranslationChecker()
        self.chinese_residue_checker = ChineseResidueChecker()
        self._checkpoint_path: Path | None = None

    def run(
        self,
        input_path: str,
        output_path: str,
        qa_report_path: str = "",
        glossary_path: str = "",
        resume: bool = True,
    ) -> Task:
        """Execute the full translation pipeline with checkpoint/resume support."""
        input_p = Path(input_path)
        self._checkpoint_path = self.config.jobs_dir / f"{input_p.stem}_checkpoint.json"

        # Install signal handler for graceful termination
        original_sigterm = signal.getsignal(signal.SIGTERM)
        _current_task = [None]  # mutable container so closure sees updates

        def sigterm_handler(signum, frame):
            log.warning("Received SIGTERM — saving checkpoint before exit")
            t = _current_task[0]
            if t and self._checkpoint_path:
                self._save_checkpoint(t)
            raise KeyboardInterrupt("SIGTERM received")

        signal.signal(signal.SIGTERM, sigterm_handler)

        start_time = time.time()

        # Try resume from checkpoint
        task = None
        if resume:
            task = self._load_checkpoint(input_path)
            if task:
                log.info(f"Resumed from checkpoint: {task.summary()}")
                log.info(f"  {sum(1 for u in task.units if u.translated_text and not u.error)}/{len(task.units)} units already translated")

        if task is None:
            task = Task(
                source_file_name=input_p.name,
                source_file_path=input_path,
            )

        # Store reference for signal handler
        _current_task[0] = task

        try:
            # Load glossary
            if glossary_path:
                self.glossary.load_yaml(glossary_path)
            elif self.config.glossary_dir:
                for pattern in ["*.yaml", "*.yml"]:
                    for gpath in self.config.glossary_dir.glob(pattern):
                        self.glossary.load_yaml(gpath)

            # Load TM
            self.tm.load()
            log.info(f"TM loaded: {self.tm.size} entries")

            # Initialize translator
            self.translator = create_translator(self.config)

            # Step 1: Extract (skip if resumed)
            if task.status in (TaskStatus.RECEIVED, TaskStatus.FAILED):
                task.set_status(TaskStatus.EXTRACTING)
                extractor = DocxExtractor(input_path)
                task.units = extractor.extract()
                task.stats["source"] = extractor.get_structure_stats()
                log.info(f"Extracted {len(task.units)} units")

            # Step 2: Translate with retry + checkpoint
            task.set_status(TaskStatus.TRANSLATING)
            self._translate_units_with_retry(task)
            self._save_checkpoint(task)

            # Step 3: QA
            if self.config.qa_enabled:
                task.set_status(TaskStatus.QA_CHECKING)
                self._run_qa(task)

            # Step 4: Write output
            task.set_status(TaskStatus.WRITING_OUTPUT)
            writer = DocxWriter(input_path, task.units)
            task.output_file_path = writer.write(output_path)

            # Post-write: scan output DOCX for residual Chinese
            if self.config.qa_enabled:
                cjk_issues = self.chinese_residue_checker.check(task.output_file_path)
                if cjk_issues:
                    log.warning(f"Post-write Chinese residue: {len(cjk_issues)} paragraphs contain CJK chars")
                task.issues.extend(cjk_issues)

            # Generate QA report
            if qa_report_path:
                task.qa_report_path = generate_report(task, qa_report_path)

            task.set_status(TaskStatus.COMPLETED)
            elapsed = time.time() - start_time
            task.stats["elapsed_seconds"] = round(elapsed, 1)
            task.stats["translator"] = self.translator.name()

            # Clean up checkpoint on success
            if self._checkpoint_path and self._checkpoint_path.exists():
                self._checkpoint_path.unlink()
                log.info("Checkpoint cleaned up")

            log.info(f"Pipeline completed in {elapsed:.1f}s: {task.summary()}")

        except KeyboardInterrupt:
            task.set_status(TaskStatus.FAILED)
            task.error = "Interrupted by user"
            self._save_checkpoint(task)
            log.warning(f"Interrupted — checkpoint saved to {self._checkpoint_path}")
            raise

        except SystemExit:
            task.set_status(TaskStatus.FAILED)
            task.error = "Terminated by system"
            self._save_checkpoint(task)
            log.warning(f"Terminated — checkpoint saved to {self._checkpoint_path}")
            raise

        except Exception as e:
            task.set_status(TaskStatus.FAILED)
            task.error = str(e)
            self._save_checkpoint(task)
            log.error(f"Pipeline failed (checkpoint saved): {e}")
            raise
        finally:
            # Restore original signal handler
            signal.signal(signal.SIGTERM, original_sigterm)

        return task

    def _translate_units_with_retry(self, task: Task):
        """Translate all units with retry logic for failures."""
        total = len(task.units)
        translated = 0
        tm_hits = 0
        errors = 0

        glossary_dict = {e.source_term: e.target_term for e in self.glossary.entries if e.active}

        # First pass
        failed_units = []
        for i, unit in enumerate(task.units):
            if not unit.source_text.strip():
                continue

            # Skip already translated (resume)
            if unit.translated_text and not unit.error:
                translated += 1
                if unit.tm_hit:
                    tm_hits += 1
                continue

            # Check TM
            tm_entry = self.tm.lookup(unit.source_text)
            if tm_entry:
                unit.translated_text = tm_entry.target_text
                unit.tm_hit = True
                unit.error = None
                tm_hits += 1
                translated += 1
                continue

            # Check glossary
            term_hits = self.glossary.lookup_text(unit.source_text)
            if term_hits:
                unit.term_hits = list(term_hits.keys())

            # Translate
            try:
                result = self._translate_with_retry(unit, glossary_dict if term_hits else None)
                unit.translated_text = result
                unit.error = None
                translated += 1

                # Add to TM
                self.tm.add(
                    source=unit.source_text,
                    target=result,
                    source_doc=task.source_file_name,
                )

            except Exception as e:
                unit.error = str(e)
                errors += 1
                failed_units.append(unit)

            # Progress + checkpoint (every 5 units or every 30 seconds, whichever comes first)
            if (i + 1) % 10 == 0 or i == total - 1:
                log.info(f"  Progress: {i + 1}/{total} ({translated} ok, {tm_hits} tm, {errors} err)")

            # More frequent checkpointing
            if (i + 1) % CHECKPOINT_EVERY == 0:
                self._save_checkpoint(task)
                log.debug(f"  Checkpoint saved at unit {i + 1}")

        # Retry failed units
        if failed_units:
            log.info(f"Retrying {len(failed_units)} failed units...")
            for attempt in range(1, MAX_RETRIES + 1):
                if not failed_units:
                    break
                backoff = min(RETRY_BACKOFF_BASE ** attempt, RETRY_BACKOFF_MAX)
                log.info(f"  Retry attempt {attempt}/{MAX_RETRIES} ({len(failed_units)} units, backoff {backoff:.0f}s)")
                time.sleep(backoff)

                retry_list = list(failed_units)
                failed_units = []
                for unit in retry_list:
                    try:
                        result = self._translate_with_retry(unit, glossary_dict if unit.term_hits else None)
                        unit.translated_text = result
                        unit.error = None
                        translated += 1
                        errors -= 1
                        log.info(f"    ✅ {unit.unit_id} recovered")
                    except Exception as e:
                        unit.error = str(e)
                        failed_units.append(unit)

            if failed_units:
                log.warning(f"  {len(failed_units)} units permanently failed after {MAX_RETRIES} retries")
                for u in failed_units:
                    log.warning(f"    ❌ {u.unit_id}: {u.error[:80] if u.error else '?'}")

        task.stats["translated"] = translated
        task.stats["tm_hits"] = tm_hits
        task.stats["errors"] = errors

        # Save TM
        self.tm.save()

    def _translate_with_retry(self, unit: TranslationUnit, glossary: dict | None = None) -> str:
        """Translate a single unit (wrapper for future retry logic in translator)."""
        return self.translator.translate(unit, glossary)

    def _save_checkpoint(self, task: Task):
        """Save task checkpoint to disk for resume capability."""
        if not self._checkpoint_path:
            return

        checkpoint = {
            "task_id": task.task_id,
            "source_file_name": task.source_file_name,
            "source_file_path": task.source_file_path,
            "status": task.status.value,
            "stats": task.stats,
            "units": [
                {
                    "unit_id": u.unit_id,
                    "part": u.part,
                    "path": u.path,
                    "source_text": u.source_text,
                    "translated_text": u.translated_text,
                    "style_name": u.style_name,
                    "context_before": u.context_before,
                    "context_after": u.context_after,
                    "term_hits": u.term_hits,
                    "tm_hit": u.tm_hit,
                    "error": u.error,
                }
                for u in task.units
            ],
            "checkpoint_time": time.time(),
        }

        self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._checkpoint_path, "w") as f:
            json.dump(checkpoint, f, ensure_ascii=False)

    def _load_checkpoint(self, input_path: str) -> Task | None:
        """Load task from checkpoint if available and matching."""
        if not self._checkpoint_path or not self._checkpoint_path.exists():
            return None

        try:
            with open(self._checkpoint_path) as f:
                data = json.load(f)

            # Verify it's the same file
            if data.get("source_file_path") != input_path:
                log.info("Checkpoint is for a different file, starting fresh")
                return None

            task = Task(
                task_id=data["task_id"],
                source_file_name=data["source_file_name"],
                source_file_path=data["source_file_path"],
                stats=data.get("stats", {}),
            )
            task.status = TaskStatus(data.get("status", "received"))

            # Restore units
            for ud in data.get("units", []):
                unit = TranslationUnit(
                    unit_id=ud["unit_id"],
                    part=ud["part"],
                    path=ud["path"],
                    source_text=ud["source_text"],
                    translated_text=ud.get("translated_text"),
                    style_name=ud.get("style_name"),
                    context_before=ud.get("context_before"),
                    context_after=ud.get("context_after"),
                    term_hits=ud.get("term_hits", []),
                    tm_hit=ud.get("tm_hit", False),
                    error=ud.get("error"),
                )
                task.units.append(unit)

            log.info(f"Loaded checkpoint from {self._checkpoint_path.name}")
            return task

        except Exception as e:
            log.warning(f"Failed to load checkpoint: {e}")
            return None

    def _run_qa(self, task: Task):
        """Run all QA checks."""
        log.info("Running QA checks...")

        target_stats = {
            "paragraphs": sum(
                1
                for u in task.units
                if u.part == UnitPart.BODY.value and u.translated_text and not u.error
            ),
            "tables": None,
            "table_cells": sum(
                1
                for u in task.units
                if u.part == UnitPart.TABLE.value and u.translated_text and not u.error
            ),
        }

        task.issues.extend(self.structure_checker.check(
            task.units, task.stats.get("source", {}), target_stats
        ))

        glossary_dict = {e.source_term: e.target_term for e in self.glossary.entries if e.active}

        for unit in task.units:
            if unit.error or not unit.translated_text:
                continue

            task.issues.extend(self.number_checker.check(unit))
            task.issues.extend(self.missing_checker.check(unit))
            if glossary_dict:
                task.issues.extend(self.term_checker.check_unit(unit, glossary_dict))

        errors = sum(1 for i in task.issues if i.severity == "error")
        warnings = sum(1 for i in task.issues if i.severity == "warning")
        log.info(f"QA complete: {errors} errors, {warnings} warnings")
