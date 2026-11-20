"""C1 / C2 checklist breakdowns (sandbox.breakdowns): treated hypertension derivation, QDiabetes smoking level,
vital plausibility; placeholder dates in the schema check; the new tables in the COPY block. The block tables of NB0 /
NB1 (smoking source, demographics, facility, C1–C2 SMD): as saved, no rate gives back a count < 10 (rate × N) and
no count < 10 is shown."""
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



SUPPRESSED = "suppressed (<10)"


class TestSmokingSource(unittest.TestCase):
    """nb01/smoking_source.csv (D28): the share of a source is hidden where its count or (cohort N − count) is < 10."""
    def snap(self, sources, conflict=()):
        s = pd.DataFrame({"smoking_source": pd.Series(sources, dtype=object)})
        s["smoking_undated_conflict"] = [i in set(conflict) for i in range(len(s))]
        return s

    def test_small_categories_and_their_rates_suppressed(self):
        # 60 patients: 48 structured, 3 diagnosis code, 4 missing, 5 conflicting undated records
        sources = ["structured"] * 48 + ["diagnosis_code"] * 3 + [None] * 9
        raw = breakdowns.smoking_source(self.snap(sources, conflict=range(55, 60)))
        self.assertEqual(dict(zip(raw["smoking_source"], raw["n"])),
                         {"structured": 48, "missing (undated conflict)": 5, "missing": 4, "diagnosis_code": 3})
        self.assertEqual(set(raw["n_cohort"]), {60})
        out = breakdowns.suppressed_shares(raw.assign(cohort="c1")).set_index("smoking_source")
        self.assertNotIn("n_cohort", out.columns)
        self.assertEqual(out.loc["structured", ["n", "pct"]].tolist(), [48, 80.0])     # 12 others: shown
        for k in ("diagnosis_code", "missing", "missing (undated conflict)"):
            self.assertEqual(out.loc[k, ["n", "pct"]].tolist(), ["<10", SUPPRESSED])
        self.assertFalse({"5.0", "6.7", "8.3"} & set(out["pct"].astype(str)))           # 3 / 4 / 5 of 60

    def test_rate_of_a_large_category_hidden_when_the_rest_is_small(self):
        out = breakdowns.suppressed_shares(breakdowns.smoking_source(self.snap(["structured"] * 55 + [None] * 5)))
        self.assertEqual(out.set_index("smoking_source").loc["structured", ["n", "pct"]].tolist(), [55, SUPPRESSED])

    def test_category_shares_with_another_denominator(self):
        r = breakdowns.category_shares(pd.Series(["age_out_of_range"] * 12), "reason", n_cohort=200)
        self.assertEqual(r.iloc[0][["n", "n_cohort", "pct"]].tolist(), [12, 200, 6.0])


class TestDemographics(unittest.TestCase):
    END = pd.Timestamp("2025-12-31")

    def patients(self, ages, males):
        dob = [self.END - pd.Timedelta(days=round(a * 365.25)) if a is not None else pd.NaT for a in ages]
        return pd.DataFrame({"patient_id": [f"P{i}" for i in range(len(ages))],
                             "sex": ["Male"] * males + ["Female"] * (len(ages) - males),
                             "date_of_birth": pd.to_datetime(pd.Series(dob))})

    def test_share_outside_the_qdiabetes_age_range(self):
        # 100 patients; whole days, so the bounds are a day inside / outside (25 <= age < 85)
        ages = [20.0] * 12 + [24.99] * 3 + [25.01] * 40 + [84.99] * 30 + [85.01] * 10 + [None] * 5
        d = breakdowns.demographics(self.patients(ages, males=50), self.END)
        self.assertEqual((d["n"], d["age_missing_n"], d["age_outside_25_84_n"], d["age_25_84_n"]), (100, 5, 25, 70))
        self.assertEqual((d["age_outside_25_84_pct"], d["age_25_84_pct"], d["male_pct"]), (25.0, 70.0, 50.0))
        out = breakdowns.suppressed_demographics(pd.DataFrame([d]))
        self.assertEqual(out.iloc[0]["age_missing_n"], "<10")
        self.assertEqual(out.iloc[0]["age_outside_25_84_pct"], 25.0)
        self.assertFalse({"age_known_n", "age_25_84_n", "male_n"} & set(out.columns))

    def test_small_cells_suppressed(self):
        # 30 patients: 4 outside 25–84, 26 inside (4 not inside → that rate hidden too), 27 men (3 women)
        d = breakdowns.demographics(self.patients([50.0] * 26 + [90.0] * 4, males=27), self.END)
        out = breakdowns.suppressed_demographics(pd.DataFrame([d])).iloc[0]
        self.assertEqual(out["age_outside_25_84_n"], "<10")
        for col in ("age_outside_25_84_pct", "age_25_84_pct", "male_pct"):
            self.assertEqual(out[col], SUPPRESSED, col)
        self.assertEqual(out["age_median"], 50.0)                     # 30 known ages: shown

    def test_median_over_few_patients_hidden(self):
        out = breakdowns.suppressed_demographics(
            pd.DataFrame([breakdowns.demographics(self.patients([40.0] * 6 + [None] * 20, males=13), self.END)]))
        self.assertEqual(out.iloc[0][["age_median", "age_iqr"]].tolist(), [SUPPRESSED, SUPPRESSED])


class TestFacility(unittest.TestCase):
    def test_not_mapped(self):
        f = breakdowns.facility_representation(pd.DataFrame({"facility_id": [None] * 40 + ["unknown"] * 10}))
        self.assertEqual((f["n_facilities"], f["facility_missing_pct"], f["top_facility_share_pct"]), (0, 100.0, None))
        out = breakdowns.suppressed_facility(pd.DataFrame([f]))
        self.assertEqual(out.columns.tolist(), ["n_facilities", "top_facility_share_pct", "facility_missing_pct"])

    def test_shares_suppressed(self):
        ids = ["F1"] * 95 + ["F2"] * 3 + [" "] * 2           # 98 known, top 95 (3 elsewhere), 2 missing
        out = breakdowns.suppressed_facility(pd.DataFrame([breakdowns.facility_representation(
            pd.DataFrame({"facility_id": ids}))])).iloc[0]
        self.assertEqual(out["n_facilities"], 2)
        self.assertEqual(out[["top_facility_share_pct", "facility_missing_pct"]].tolist(), [SUPPRESSED, SUPPRESSED])
        ok = breakdowns.facility_representation(pd.DataFrame({"facility_id": ["F1"] * 60 + ["F2"] * 25 + [None] * 15}))
        self.assertEqual((ok["top_facility_share_pct"], ok["facility_missing_pct"]), (70.6, 15.0))   # 60 / 85


class TestSelectionEffect(unittest.TestCase):
    def test_smd_and_small_shares(self):
        f1 = pd.DataFrame({"age": [40.0, 60.0] * 25, "rare": [True] * 3 + [False] * 47,
                           "common": [True] * 25 + [False] * 25})
        f2 = pd.DataFrame({"age": [45.0, 65.0] * 25, "rare": [True] * 12 + [False] * 38,
                           "common": [True] * 20 + [False] * 30})
        sel = breakdowns.selection_effect(f1, f2).set_index("variable")
        self.assertEqual(sel.loc["age", "type"], "continuous")
        self.assertEqual(sel.loc["rare", "type"], "binary")
        self.assertAlmostEqual(sel.loc["age", "smd"], round(-5 / pd.Series([40.0, 60.0] * 25).std(), 3))
        p1, p2 = 0.5, 0.4
        self.assertAlmostEqual(sel.loc["common", "smd"], round((p1 - p2) / ((p1 * .5 + p2 * .6) / 2) ** .5, 3))
        self.assertTrue(sel.loc["rare", "imbalance"])                  # |SMD| > 0.1
        out = breakdowns.suppressed_selection_effect(sel.reset_index()).set_index("variable")
        self.assertEqual(out.loc["rare", ["c1", "smd"]].tolist(), [SUPPRESSED, SUPPRESSED])   # 3 of 50 in C1
        self.assertEqual(out.loc["rare", "c2"], 0.24)                  # 12 of 50: shown
        self.assertTrue(out.loc["rare", "imbalance"])                  # the flag stays
        self.assertEqual(out.loc["common", ["c1", "c2"]].tolist(), [0.5, 0.4])
        self.assertFalse({"c1_k", "c2_k"} & set(out.columns))
        self.assertNotIn(0.06, out["c1"].tolist())

    def test_feature_with_missing_values(self):
        """A nullable boolean (ethnicity unknown → NA) is binary over the patients with a value."""
        f = pd.DataFrame({"eth": pd.array([True] * 20 + [False] * 20 + [None] * 10, dtype="boolean")})
        sel = breakdowns.selection_effect(f, f).iloc[0]
        self.assertEqual((sel["type"], sel["c1"], sel["c1_n"], sel["c1_k"], sel["smd"]), ("binary", 0.5, 40, 20, 0.0))


if __name__ == "__main__":
    unittest.main()
