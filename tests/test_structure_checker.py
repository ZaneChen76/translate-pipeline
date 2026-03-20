import unittest
from typing import Optional

from app.core import TranslationUnit
from app.qa.checks import StructureChecker


def _unit(uid: str, part: str, src: str = "x", tgt: Optional[str] = "y") -> TranslationUnit:
    return TranslationUnit(
        unit_id=uid,
        part=part,
        path=f"{part}/p[0]",
        source_text=src,
        translated_text=tgt,
    )


class StructureCheckerTest(unittest.TestCase):
    def test_reports_mismatch_when_target_counts_zero(self):
        checker = StructureChecker()
        units = [_unit("u1", "body"), _unit("u2", "table")]
        source_stats = {"paragraphs": 1, "tables": 1, "table_cells": 1}
        target_stats = {"paragraphs": 0, "tables": 1, "table_cells": 0}

        issues = checker.check(units, source_stats, target_stats)
        details = [i.detail for i in issues]

        self.assertTrue(any("Paragraph count mismatch" in d for d in details))
        self.assertTrue(any("Table cell count mismatch" in d for d in details))


if __name__ == "__main__":
    unittest.main()
