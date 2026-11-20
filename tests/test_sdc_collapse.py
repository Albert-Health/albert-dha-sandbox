"""sdc.collapse_rare_rows: a source label seen in fewer than 10 patients in every cohort is not printed; its counts
go into one merged row per group, so totals still add up (NB1 nb01/ethnicity_mapping_by_source.csv).
sdc.safe_rate / suppress_small_group_stats: a rate whose count or (N − count) is < 10 and a median over < 10 patients
are not printed (KPI text, NB0 demographics, NB1 score_summary)."""
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



class TestRatesAndGroupStats(unittest.TestCase):
    def test_safe_rate(self):
        self.assertEqual(sdc.safe_rate(40.0, 8, 20), "suppressed (<10)")          # 8 patients
        self.assertEqual(sdc.safe_rate(85.0, 17, 20), "suppressed (<10)")         # 3 without
        self.assertEqual(sdc.safe_rate(50.0, 10, 20), 50.0)
        self.assertEqual(sdc.safe_rate(0.0, 0, 2600), 0.0)                        # 0 is not a small cell
        self.assertEqual(sdc.safe_rate(100.0, 2600, 2600), 100.0)
        self.assertEqual(sdc.safe_rate(12.5, None, 200), 12.5)                    # no count: as before

    def test_small_group_stats(self):
        df = pd.DataFrame({"g": ["a", "b", "c"], "n": [4, 30, 0], "median": [61.0, 55.5, None]})
        out = sdc.suppress_small_group_stats(df, "n", ["median"])
        self.assertEqual(out["median"].tolist()[:2], ["suppressed (<10)", 55.5])
        self.assertTrue(pd.isna(out["median"].iloc[2]))


if __name__ == "__main__":
    unittest.main()
