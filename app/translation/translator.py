from __future__ import annotations
"""Translator interface and implementations."""

import re
import time
from abc import ABC, abstractmethod
from typing import Optional

from ..core import TranslationUnit
from ..core.config import Config, log

# System prompt for strict translation
TRANSLATE_SYSTEM_PROMPT = """You are a professional Chinese-to-English translator for technical documents and business proposals.

STRICT RULES:
1. Translate the Chinese text into natural, professional English
2. Preserve ALL numbers, units, dates, percentages, amounts, and model numbers EXACTLY
3. Keep product names, brand names, and code identifiers in original form
4. Use formal technical/business register - no casual language
5. Do NOT add explanations, notes, or commentary
6. Do NOT omit or expand content - translate exactly what is given
7. Follow terminology from the provided glossary if present
8. Output ONLY the translation, nothing else"""

GLOSSARY_INSTRUCTION = """
GLOSSARY TERMS (must use these exact translations):
{glossary_entries}
"""

CONTEXT_INSTRUCTION = """
CONTEXT (for reference only, do not translate):
Previous: {context_before}
Next: {context_after}
"""


class Translator(ABC):
    """Abstract translator interface."""

    @abstractmethod
    def translate(self, unit: TranslationUnit, glossary: Optional[dict] = None) -> str:
        """Translate a single unit. Returns translated text."""
        ...

    @abstractmethod
    def name(self) -> str:
        ...


class MockTranslator(Translator):
    """Mock translator for testing - returns source text with [EN] prefix."""

    def translate(self, unit: TranslationUnit, glossary: Optional[dict] = None) -> str:
        return f"[EN] {unit.source_text}"

    def name(self) -> str:
        return "mock"


class HunyuanLiteTranslator(Translator):
    """Tencent Hunyuan Lite translator via OpenAI-compatible API."""

    def __init__(self, config: Config):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package required: pip install openai")

        if not config.hunyuan_api_key:
            raise ValueError("HUNYUAN_API_KEY not set")

        self.client = OpenAI(
            api_key=config.hunyuan_api_key,
            base_url=config.hunyuan_base_url,
            timeout=config.translation_timeout,
        )
        self.model = config.hunyuan_model
        self.temperature = config.temperature
        self.top_p = config.top_p
        self._last_call_time = 0.0

    def translate(self, unit: TranslationUnit, glossary: Optional[dict] = None) -> str:
        # Build prompt
        system_parts = [TRANSLATE_SYSTEM_PROMPT]

        if glossary:
            entries = "\n".join(
                f"- {src} → {tgt}" for src, tgt in glossary.items()
            )
            system_parts.append(GLOSSARY_INSTRUCTION.format(glossary_entries=entries))

        if unit.context_before or unit.context_after:
            system_parts.append(
                CONTEXT_INSTRUCTION.format(
                    context_before=unit.context_before or "(none)",
                    context_after=unit.context_after or "(none)",
                )
            )

        # Rate limiting: min 200ms between calls
        elapsed = time.time() - self._last_call_time
        if elapsed < 0.2:
            time.sleep(0.2 - elapsed)

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "\n".join(system_parts)},
                    {"role": "user", "content": unit.source_text},
                ],
                temperature=self.temperature,
                top_p=self.top_p,
            )
            self._last_call_time = time.time()

            translation = resp.choices[0].message.content
            if not translation:
                raise ValueError("Empty translation response")
            return translation.strip()

        except Exception as e:
            log.error(f"Translation failed for {unit.unit_id}: {e}")
            raise

    def name(self) -> str:
        return f"hunyuan-lite ({self.model})"


def create_translator(config: Config) -> Translator:
    """Factory function to create translator based on config."""
    if config.translator == "mock":
        log.info("Using MockTranslator")
        return MockTranslator()
    elif config.translator == "hunyuan":
        log.info(f"Using HunyuanLiteTranslator ({config.hunyuan_model})")
        return HunyuanLiteTranslator(config)
    else:
        raise ValueError(f"Unknown translator: {config.translator}")
