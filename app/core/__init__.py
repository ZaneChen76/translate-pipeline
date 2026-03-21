"""Core data models for TranslatePipeline."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid
import typing


class TaskStatus(str, Enum):
    RECEIVED = "received"
    EXTRACTING = "extracting"
    TRANSLATING = "translating"
    QA_CHECKING = "qa_checking"
    WRITING_OUTPUT = "writing_output"
    COMPLETED = "completed"
    FAILED = "failed"


class UnitPart(str, Enum):
    BODY = "body"
    HEADER = "header"
    FOOTER = "footer"
    TABLE = "table"
    TEXTBOX = "textbox"
    FOOTNOTE = "footnote"
    ENDNOTE = "endnote"


@dataclass
class TranslationUnit:
    """A single translatable unit (paragraph or table cell)."""
    unit_id: str
    part: str  # UnitPart
    path: str  # Location in docx (e.g., "body/p[5]", "table[0]/cell[2,3]")
    source_text: str
    translated_text: Optional[str] = None
    style_name: Optional[str] = None
    context_before: Optional[str] = None
    context_after: Optional[str] = None
    term_hits: list[str] = field(default_factory=list)
    tm_hit: bool = False
    tm_match_type: typing.Optional[str] = None
    tm_similarity: typing.Optional[float] = None
    error: Optional[str] = None

    @property
    def is_heading(self) -> bool:
        return bool(self.style_name and self.style_name.startswith("Heading"))

    @property
    def is_table_cell(self) -> bool:
        return self.part == UnitPart.TABLE


@dataclass
class GlossaryEntry:
    """A single glossary term mapping."""
    source_term: str
    target_term: str
    domain: Optional[str] = None
    project_id: Optional[str] = None
    case_sensitive: bool = False
    notes: Optional[str] = None
    active: bool = True


@dataclass
class TmEntry:
    """A translation memory entry (exact match)."""
    source_text: str
    target_text: str
    source_doc: Optional[str] = None
    confirmed: bool = False
    hit_count: int = 0


@dataclass
class QaIssue:
    """A single QA issue found during checking."""
    severity: str  # "error", "warning", "info"
    category: str  # "structure", "number", "term", "missing", "extra"
    unit_id: Optional[str] = None
    detail: str = ""
    source_snippet: Optional[str] = None
    target_snippet: Optional[str] = None


@dataclass
class Task:
    """A translation task."""
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    source_channel: str = "cli"
    source_file_name: str = ""
    source_file_path: str = ""
    output_file_path: Optional[str] = None
    qa_report_path: Optional[str] = None
    status: TaskStatus = TaskStatus.RECEIVED
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    units: list[TranslationUnit] = field(default_factory=list)
    issues: list[QaIssue] = field(default_factory=list)
    error: Optional[str] = None
    stats: dict = field(default_factory=dict)

    def set_status(self, status: TaskStatus):
        self.status = status
        self.updated_at = datetime.now()

    def add_issue(self, issue: QaIssue):
        self.issues.append(issue)

    def summary(self) -> str:
        errors = sum(1 for i in self.issues if i.severity == "error")
        warnings = sum(1 for i in self.issues if i.severity == "warning")
        return (
            f"Task {self.task_id}: {self.status.value} | "
            f"{len(self.units)} units | "
            f"{errors} errors, {warnings} warnings"
        )
