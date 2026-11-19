"""src/sandbox/io/explore.py: column kind guess (enclave.sh values / columns)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from sandbox.io import explore  # noqa: E402


class TestKind(unittest.TestCase):
    def test_eight_digit_snomed_is_not_a_date(self):
        """NABIDH FamilyHistory.Diagnosis_Code (2026-11-19): 8-digit SNOMED codes were taken for dates (YYYYMMDD)."""
        codes = pd.Series(["73211009"] * 40 + ["44054006"] * 15 + ["60376773"] * 10 + ["DIABETES"] * 15 + ["Z83.3"] * 5)
        self.assertEqual(explore.profile_column("Diagnosis_Code", codes)["kind"], "code")
        self.assertNotEqual(explore.profile_column("Comment", codes)["kind"], "date")      # invalid date

    def test_numeric_code_column_lists_values(self):
        codes = pd.Series([str(10000000 + i) for i in range(30)] * 2)
        self.assertEqual(explore.profile_column("DrugProduct_Code", codes)["kind"], "code")

    def test_real_yyyymmdd_and_iso_dates(self):
        ymd = pd.Series([f"2021{m:02d}{d:02d}" for m in range(1, 13) for d in (1, 15)])
        self.assertEqual(explore.profile_column("ResultDate", ymd)["kind"], "date")
        self.assertEqual(explore.profile_column("Extra", ymd)["kind"], "date")              # even without a name hint
        iso = pd.Series(["2023-01-05 10:00:00"] * 20)
        self.assertEqual(explore.profile_column("EnteredOn", iso)["kind"], "date")

    def test_decimal_values_stay_numeric(self):
        vals = pd.Series([f"{5 + i * 0.1:.1f}" for i in range(40)])
        self.assertEqual(explore.profile_column("ResultValue", vals)["kind"], "number")


if __name__ == "__main__":
    unittest.main()
