"""sdc.collapse_rare_rows: a source label seen in fewer than 10 patients in every cohort is not printed; its counts
go into one merged row per group, so totals still add up (NB1 nb01/ethnicity_mapping_by_source.csv)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from sandbox import sdc  # noqa: E402


class TestCollapseRareRows(unittest.TestCase):
    def table(self):
        return pd.DataFrame({
            "source": ["ethnicity"] * 4 + ["nationality"] * 2,
            "value": ["Indian", "Rareland", "Tinyland", "Emirati", "<missing>", "Nepal"],
            "c1": [40, 3, 2, 9, 120, 4],
            "c2": [35, 1, 0, 12, 118, 5],
        })

    def test_rare_labels_merged_per_group(self):
        out = sdc.collapse_rare_rows(self.table(), ["c1", "c2"], ["value"], by=["source"])
        self.assertNotIn("Rareland", out["value"].tolist())
        self.assertNotIn("Tinyland", out["value"].tolist())
        self.assertNotIn("Nepal", out["value"].tolist())
        self.assertIn("Emirati", out["value"].tolist())                  # 12 patients in c2 → kept
        merged = out[out["value"].str.startswith("(values with")].set_index("source")
        self.assertEqual(merged.loc["ethnicity", ["c1", "c2"]].tolist(), [5, 1])
        self.assertEqual(merged.loc["nationality", ["c1", "c2"]].tolist(), [4, 5])
        self.assertEqual(out["c1"].sum(), self.table()["c1"].sum())       # totals unchanged
        shown = sdc.suppress_small_counts(out, ["c1", "c2"])
        self.assertEqual(shown.set_index(["source", "value"]).loc[("ethnicity", "(values with < 10 patients each)"), "c1"],
                         "<10")

    def test_nothing_rare(self):
        df = self.table().iloc[[0, 4]]
        out = sdc.collapse_rare_rows(df, ["c1", "c2"], ["value"], by=["source"])
        self.assertEqual(out["value"].tolist(), ["Indian", "<missing>"])


if __name__ == "__main__":
    unittest.main()
