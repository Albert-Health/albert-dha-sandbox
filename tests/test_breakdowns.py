"""C1 / C2 checklist breakdowns (sandbox.breakdowns): treated hypertension derivation, QDiabetes smoking level,
vital plausibility; placeholder dates in the schema check; the new tables in the COPY block."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import enclave  # noqa: E402
from sandbox import breakdowns, phenotype  # noqa: E402
from sandbox.config import PARAMS  # noqa: E402
from sandbox.io import schema  # noqa: E402
from sandbox.scores import lprs, lrs, qdiabetes2018a as qd  # noqa: E402

REF = pd.Timestamp("2020-12-31")


def dataset(ids, conditions=(), medications=(), observations=()) -> schema.Dataset:
    """Hand-made canonical dataset: male patients born 1960-01-01; rows as tuples."""
    t = {
        "patients": pd.DataFrame({"patient_id": list(ids), "sex": "Male", "date_of_birth": "1960-01-01"}),
        "conditions": pd.DataFrame(list(conditions), columns=["patient_id", "code", "date"])
                      .assign(code_system="ICD-10"),
        "medications": pd.DataFrame(list(medications), columns=["patient_id", "atc_code", "date"]),
        "observations": pd.DataFrame(list(observations), columns=["patient_id", "concept", "value", "date"]),
        "labs": pd.DataFrame(), "encounters": pd.DataFrame(),
    }
    return schema.Dataset(source="t", cohort="c1", tables={k: schema.coerce(v, k) for k, v in t.items()})


def snapshot(ds, p=PARAMS):
    ids = ds["patients"]["patient_id"]
    return phenotype.core_snapshot(ds, pd.Series(REF, index=ids.to_numpy()), None, p)


class TestHtnDerivation(unittest.TestCase):
    CATEGORY = {"A": "diagnosis only", "B": "medication only", "C": "diagnosis and medication", "D": "neither"}

    def setUp(self):
        ds = dataset("ABCD", conditions=[("A", "I10", "2019-01-01"), ("C", "I11.9", "2019-01-01")],
                     medications=[("B", "C09AA02", "2019-02-01"), ("C", "C07AB02", "2019-02-01")])
        self.snap = snapshot(ds)

    def test_counted_by_matches_phenotype_and_scorers(self):
        """HTN_COUNTED_BY is a label: it must say what the code does (snapshot columns and the score inputs)."""
        s = self.snap
        used = {"QDiabetes": qd.prepare_inputs(s)["htn"].astype(bool),
                "LPRS": lprs.score(s)["lrs_htn"].gt(0),
                "LRA 2010": lrs.score_assessment_2010(s)["lrs_htn"].gt(0)}
        for score, col in breakdowns.HTN_SCORE_COLUMN.items():
            for pid, cat in self.CATEGORY.items():
                want = cat in breakdowns.HTN_COUNTED_BY[score]
                self.assertEqual(bool(s.loc[pid, col]), want, (score, pid))
                self.assertEqual(bool(used[score][pid]), want, (score, pid))

    def test_table(self):
        t = breakdowns.htn_derivation(self.snap.assign(status=["T2DM", "T2DM", "Prediabetes", "Prediabetes"]))
        a = t[t["group"] == "all"].set_index("htn_category")
        self.assertEqual(list(a.index), list(breakdowns.HTN_CATEGORIES))
        self.assertEqual(a["n"].tolist(), [1, 1, 1, 1])
        self.assertEqual(a["pct"].tolist(), [25.0] * 4)
        self.assertEqual(a["counted_as_treated_by"].tolist(),
                         ["LRA 2010", "LPRS, LRA 2010", "QDiabetes, LPRS, LRA 2010", "none"])
        t2 = t[t["group"] == "T2DM"].set_index("htn_category")
        self.assertEqual(t2["n"].tolist(), [1, 1, 0, 0])
        self.assertEqual(set(t2["n_group"]), {2})


class TestSmokingLevel(unittest.TestCase):
    def setUp(self):
        self.ds = dataset(
            ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9"],
            conditions=[("P2", "Z87.891", "2019-01-01")],                     # ex-smoker only from a diagnosis code
            observations=[("P1", "smoking_status", "never", "2019-01-01"),
                          ("P3", "smoking_status", "light", "2019-01-01"),
                          ("P4", "smoking_status", "moderate", "2019-01-01"),
                          ("P5", "smoking_status", "current", "2019-01-01"),   # no intensity → D7 category
                          ("P6", "smoking_status", "unknown", "2019-01-01"),
                          ("P7", "smoking_status", "unmapped:other", "2019-01-01"),
                          ("P9", "smoking_status", "never", None),              # undated, disagree → missing
                          ("P9", "smoking_status", "heavy", None)])

    def table(self, p=PARAMS):
        t = breakdowns.smoking_levels(snapshot(self.ds, p), self.ds["observations"], p)
        return {(r.qd_smoking_level, r.recorded_as): (r.n, r.n_from_diagnosis_code) for r in t.itertuples()}, t

    def test_levels(self):
        got, t = self.table()
        self.assertEqual(got, {
            ("non", "never"): (1, 0), ("ex", "ex"): (1, 1), ("light", "light"): (1, 0),
            ("moderate", "moderate"): (1, 0), ("moderate", "current, intensity not recorded (D7 → moderate)"): (1, 0),
            ("heavy", "-"): (0, 0),                                              # every level appears
            ("missing", "records present, none usable (unknown / unmapped, e.g. other)"): (2, 0),
            ("missing", "no smoking record"): (1, 0), ("missing", "undated records disagree (D28)"): (1, 0)})
        self.assertEqual(t["qd_smoking_level"].drop_duplicates().tolist(), breakdowns.SMOKING_LEVEL_ORDER)
        self.assertEqual(set(t["n_cohort"]), {9})
        self.assertAlmostEqual(t.loc[t["recorded_as"] == "no smoking record", "pct"].iloc[0], round(100 / 9, 1))

    def test_follows_d7_and_d8(self):
        got, _ = self.table(dict(PARAMS, qd_smoking_current_category=4, qd_missing_smoking_as_non=True))
        self.assertIn(("heavy", "current, intensity not recorded (D7 → heavy)"), got)
        self.assertEqual(got[("non", "no smoking record")], (1, 0))            # D8: missing counted as non
        self.assertEqual(got[("missing", "-")], (0, 0))


class TestVitalPlausibility(unittest.TestCase):
    def test_counts_and_snapshot_use_the_same_range(self):
        ds = dataset(["V1", "V2", "V3"], observations=[
            ("V1", "bmi", "25", "2019-01-01"), ("V1", "bmi", "90", "2020-01-01"),   # above; a plausible value remains
            ("V2", "bmi", "5", "2019-01-01"),                                       # below; nothing plausible left
            ("V3", "bmi", "abc", "2019-01-01"),                                     # not a number
            ("V1", "height_cm", "165", "2019-01-01"), ("V2", "height_cm", "1.65", "2019-01-01"),
            ("V1", "weight_kg", "400", "2019-01-01")])
        t = breakdowns.vital_plausibility(ds).set_index("variable")
        self.assertEqual(list(t.index), list(phenotype.VITAL_PLAUSIBLE_RANGE))
        self.assertEqual(t.loc["bmi", "plausible_range"], "12–80")
        cols = ["rows", "rows_out_of_range", "rows_below", "rows_non_numeric", "patients", "patients_out_of_range",
                "patients_without_plausible_value"]
        self.assertEqual(t.loc["bmi", cols].tolist(), [4, 2, 1, 1, 3, 2, 2])
        self.assertEqual(t.loc["height_cm", cols].tolist(), [2, 1, 1, 0, 2, 1, 1])
        self.assertEqual(t.loc["weight_kg", cols].tolist(), [1, 1, 0, 0, 1, 1, 1])
        self.assertEqual(t.loc["waist_cm", cols].tolist(), [0] * 7)
        s = snapshot(ds)
        self.assertEqual(s.loc["V1", "bmi"], 25.0)                       # 90 left out, as counted
        self.assertTrue(s.loc[["V2", "V3"], "bmi"].isna().all())


class TestPlaceholderDates(unittest.TestCase):
    def test_counted_not_dropped(self):
        ds = dataset("XY", conditions=[("X", "I10", "1970-01-01"), ("X", "E11.9", "1970-01-01"),
                                       ("Y", "I10", "1900-01-01"), ("Y", "I10", "2019-01-01")])
        with tempfile.TemporaryDirectory() as d:
            schema.write_dataset(ds, Path(d))
            back = schema.read_dataset(Path(d), "t", "c1")
        self.assertEqual(len(back["conditions"]), 4)                     # rows kept
        v = schema.validate(back).set_index(["table", "check"])
        epoch = v.loc[("conditions", "date exactly 1970-01-01 (placeholder? counted, kept)")]
        self.assertEqual((epoch["severity"], epoch["n_affected"]), ("WARN", 2))
        y1900 = v.loc[("conditions", "date exactly 1900-01-01 (placeholder? counted, kept)")]
        self.assertEqual((y1900["severity"], y1900["n_affected"]), ("WARN", 1))
        self.assertEqual(v.loc[("conditions", "implausible date"), "severity"], "INFO")   # 1900-01-01 is not < 1900
        dob = v.loc[("patients", "date_of_birth exactly 1970-01-01 (placeholder? counted, kept)")]
        self.assertEqual((dob["severity"], dob["n_affected"]), ("INFO", 0))
        self.assertFalse((v["severity"] == "ERROR").any())


class TestBlockTables(unittest.TestCase):
    def test_new_tables_in_block_suppressed(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "nb01").mkdir()
            (d / "nb00").mkdir()
            pd.DataFrame({"cohort": "c1", "group": ["all", "all", "T2DM"], "htn_category": ["both", "neither", "both"],
                          "n": [3, 120, 2], "n_group": [123, 123, 50], "pct": ["suppressed (<10)", 97.6, "x"],
                          "counted_as_treated_by": ["QDiabetes, LPRS, LRA 2010", "none", "x"]}
                         ).to_csv(d / "nb01" / "htn_derivation.csv", index=False)
            pd.DataFrame({"cohort": "c1", "qd_smoking_level": ["ex"], "recorded_as": ["ex"], "n": [4], "pct": ["x"],
                          "n_from_diagnosis_code": [4]}).to_csv(d / "nb01" / "smoking_level.csv", index=False)
            pd.DataFrame({"cohort": "c1", "variable": ["bmi"], "plausible_range": ["12–80"], "rows": [500],
                          "rows_out_of_range": [7], "rows_below": [3], "rows_non_numeric": [0], "patients": [300],
                          "patients_out_of_range": [6], "patients_without_plausible_value": [2]}
                         ).to_csv(d / "nb00" / "vital_plausibility.csv", index=False)
            block = enclave.Block("HEADER")
            with contextlib.redirect_stdout(io.StringIO()):
                enclave.summary_tables("nb1")(d, block, mock.Mock(max_rows=60))
                enclave.summary_tables("nb0")(d, block, mock.Mock(max_rows=60))
        text = "\n".join(block.lines)
        self.assertIn("-- nb01/htn_derivation.csv (2 rows)", text)            # group_all: T2DM rows left out
        self.assertIn("-- nb01/smoking_level.csv (1 rows)", text)
        self.assertIn("-- nb00/vital_plausibility.csv (1 rows)", text)
        self.assertNotIn("T2DM", text)
        for small in (" 3 ", " 4 ", " 7 ", " 6 ", " 2 "):
            self.assertNotIn(small, text.replace("\n", " ") + " ")


if __name__ == "__main__":
    unittest.main()
