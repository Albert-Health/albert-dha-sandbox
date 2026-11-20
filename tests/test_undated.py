"""Rows without a date (VM ingest 1.3.0, 2026-11-20: NB0 stopped on "missing required date").
Claim: the adapter drops and counts undated rows the analysis cannot place in time, but keeps undated family
history (D27) and smoking (D28); the schema check reports those two as INFO, so NB0 does not stop on them."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from sandbox.io import schema  # noqa: E402
from sandbox.io.adapters import nabidh  # noqa: E402

T0 = pd.Timestamp("2022-03-01")


def obs(rows):
    return pd.DataFrame(rows, columns=["patient_id", "concept", "value", "date"])


class TestDropUndated(unittest.TestCase):
    def test_keeps_fh_and_smoking_drops_the_rest(self):
        produced = {
            "observations": obs([["A", "bmi", "27", T0], ["A", "bmi", "28", pd.NaT],
                                 ["A", "smoking_status", "never", pd.NaT],
                                 ["B", "family_history_dm", "positive", pd.NaT]]),
            "conditions": pd.DataFrame({"patient_id": ["A", "B"], "code": ["E11.9", "I10"],
                                        "date": [T0, pd.NaT]}),
        }
        info = {}
        out = nabidh.drop_undated(produced, info)
        self.assertEqual(info["dropped_no_date"], 2)                       # one BMI, one diagnosis
        self.assertEqual(sorted(out["observations"]["concept"]), ["bmi", "family_history_dm", "smoking_status"])
        self.assertEqual(out["observations"].query("concept == 'bmi'")["value"].tolist(), ["27"])
        self.assertEqual(out["conditions"]["patient_id"].tolist(), ["A"])

    def test_nothing_to_drop(self):
        info = {}
        out = nabidh.drop_undated({"conditions": pd.DataFrame({"patient_id": ["A"], "date": [T0]}),
                                   "observations": obs([])}, info)
        self.assertEqual(info["dropped_no_date"], 0)
        self.assertEqual(len(out["conditions"]), 1)


class TestUndatedSchemaCheck(unittest.TestCase):
    def dataset(self, observations):
        tables = {t: schema.coerce(pd.DataFrame(columns=list(schema.SCHEMA[t])), t) for t in schema.TABLES}
        tables["patients"] = schema.coerce(pd.DataFrame({"patient_id": ["A"], "sex": ["Male"],
                                                         "date_of_birth": ["1970-01-01"]}), "patients")
        tables["observations"] = schema.coerce(observations, "observations")
        return schema.Dataset(source="t", cohort="c1", tables=tables)

    def test_undated_smoking_and_fh_are_info(self):
        val = schema.validate(self.dataset(obs([["A", "smoking_status", "never", pd.NaT],
                                                ["A", "family_history_dm", "positive", pd.NaT]])))
        obs_val = val[val["table"] == "observations"].set_index("check")
        self.assertEqual(obs_val.loc["smoking record without date (used only if all agree, D28)", "severity"], "INFO")
        self.assertEqual(obs_val.loc["smoking record without date (used only if all agree, D28)", "n_affected"], 1)
        self.assertEqual(obs_val.loc["missing required date", "severity"], "INFO")
        self.assertFalse((val["severity"] == "ERROR").any())

    def test_undated_vital_is_still_an_error(self):
        val = schema.validate(self.dataset(obs([["A", "bmi", "27", pd.NaT]])))
        row = val[(val["table"] == "observations") & (val["check"] == "missing required date")].iloc[0]
        self.assertEqual((row["severity"], row["n_affected"]), ("ERROR", 1))


if __name__ == "__main__":
    unittest.main()
