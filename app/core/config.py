from __future__ import annotations
"""Configuration and logging for TranslatePipeline."""

import logging
import os
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class Config:
    """Pipeline configuration."""
    # Paths
    data_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent / "data")
    glossary_dir: Optional[Path] = None
    tm_dir: Optional[Path] = None
    output_dir: Optional[Path] = None
    jobs_dir: Optional[Path] = None

    # Translation
    translator: str = "hunyuan"  # "mock" or "hunyuan"
    hunyuan_api_key: str = ""
    hunyuan_base_url: str = "https://api.hunyuan.cloud.tencent.com/v1"
    hunyuan_model: str = "hunyuan-lite"
    temperature: float = 0.3
    top_p: float = 0.9
    translation_timeout: int = 120  # seconds, per API call

    # QA
    qa_enabled: bool = True
    tm_similarity_threshold: float = 0.85
    qa_weights: dict | None = None

    def __post_init__(self):
        # Normalize YAML-loaded string paths
        if isinstance(self.data_dir, str):
            self.data_dir = Path(self.data_dir)
        if isinstance(self.glossary_dir, str):
            self.glossary_dir = Path(self.glossary_dir)
        if isinstance(self.tm_dir, str):
            self.tm_dir = Path(self.tm_dir)
        if isinstance(self.output_dir, str):
            self.output_dir = Path(self.output_dir)
        if isinstance(self.jobs_dir, str):
            self.jobs_dir = Path(self.jobs_dir)

        if self.glossary_dir is None:
            self.glossary_dir = self.data_dir / "glossary"
        if self.tm_dir is None:
            self.tm_dir = self.data_dir / "tm"
        if self.output_dir is None:
            self.output_dir = self.data_dir / "output"
        if self.jobs_dir is None:
            self.jobs_dir = self.data_dir / "jobs"

        # Ensure dirs exist
        for d in [self.glossary_dir, self.tm_dir, self.output_dir, self.jobs_dir]:
            d.mkdir(parents=True, exist_ok=True)


        # Other overrides from env (if provided)
        tr_env = os.environ.get('TRANSLATE_PIPELINE_TRANSLATOR')
        if tr_env:
            self.translator = tr_env
        tmt = os.environ.get('TM_SIMILARITY_THRESHOLD') or os.environ.get('TRANSLATE_PIPELINE_TM_THRESHOLD')
        if tmt:
            try:
                self.tm_similarity_threshold = float(tmt)
            except ValueError:
                pass
        # API key from env
        if not self.hunyuan_api_key:
            self.hunyuan_api_key = os.environ.get("HUNYUAN_API_KEY", "")

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in allowed})


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure structured logging."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt))

    logger = logging.getLogger("translate_pipeline")
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False

    return logger


log = setup_logging()
