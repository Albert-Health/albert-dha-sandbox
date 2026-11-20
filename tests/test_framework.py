"""Framework Match by variable (framework.py): Match / Partial / Absent, hand-made cohorts with known answers."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from sandbox import codelists, framework, kpi  # noqa: E402
from sandbox.config import PARAMS  # noqa: E402
from sandbox.io import schema  # noqa: E402
from sandbox.io.adapters import nabidh  # noqa: E402
from sandbox.io.schema import Dataset, coerce  # noqa: E402

N = 50                                      # patients per hand-made cohort
ALL_LEVELS = ["never", "ex", "light", "moderate", "heavy"] * 10          # 10 patients per smoking level
SMOKING = ["never"] * 14 + ["ex"] * 14 + ["light"] * 11 + ["moderate"] * 11      # no "heavy" smoker
NATIONALITY = ["United Arab Emirates"] * N


def make_ds(nationality=NATIONALITY, ethnicity=None, smoking=SMOKING, fh_value="positive", htn_dx=True, htn_med=True,
            cvd=True) -> Dataset:
    ids = [f"P{i:02d}" for i in range(N)]
    pts = pd.DataFrame({"patient_id": ids, "sex": ["Male", "Female"] * (N // 2), "date_of_birth": "1970-01-01",
                        "ethnicity_raw": ethnicity or [None] * N, "nationality": nationality,
                        "facility_id": None})
    obs = [(i, "bmi", "27.5", "2020-01-01") for i in ids]
    obs += [(i, "smoking_status", s, "2020-01-01") for i, s in zip(ids, smoking)]
    obs += [(i, "family_history_dm", fh_value, "2020-01-01") for i in ids[:30]]
    obs = pd.DataFrame(obs, columns=["patient_id", "concept", "value", "date"])
    cond = [(i, "ICD-10", "I10", "2019-01-01") for i in ids[:30]] if htn_dx else []
    cond += [(i, "ICD-10", "I25.9", "2019-01-01") for i in ids[:5]] if cvd else []
    meds = [(i, "C09AA02", "2019-02-01") for i in ids[:30]] if htn_med else []
    tables = {
        "patients": coerce(pts, "patients"),
        "conditions": coerce(pd.DataFrame(cond, columns=["patient_id", "code_system", "code", "date"]), "conditions"),
        "medications": coerce(pd.DataFrame(meds, columns=["patient_id", "atc_code", "date"]), "medications"),
        "observations": coerce(obs, "observations"),
        "labs": coerce(pd.DataFrame(), "labs"),
        "encounters": coerce(pd.DataFrame(), "encounters"),
    }
    return Dataset(source="test", cohort="c1", tables=tables)


def by_var(table: pd.DataFrame, cohort="c1") -> pd.DataFrame:
    return table[table["cohort"] == cohort].set_index("variable")


FULL = {"medications": {"requested_system": "ATC", "rows": 100, "as_requested_rows": 100},
        "family_history": {"requested_system": "ICD-10 / SNOMED code", "rows": 100, "as_requested_rows": 100}}


class TestMatchByVariable(unittest.TestCase):
    def test_all_match(self):
        t = by_var(framework.match_table({"c1": make_ds(smoking=ALL_LEVELS)},
                                         {"c1": FULL}))
        self.assertEqual(list(t.index), codelists.CORE_VARIABLES)
        self.assertEqual(set(t["status"]), {"Match"}, t[["status", "reason"]].to_string())
        self.assertEqual(framework.overall(t.reset_index()), "Match")
        self.assertEqual(framework.non_match(t.reset_index()), {})

    def test_without_delivery_facts_counts_as_requested(self):
        t = by_var(framework.match_table({"c1": make_ds(smoking=ALL_LEVELS)}))
        self.assertEqual(set(t["status"]), {"Match"})           # a source with no facts (synthetic)
        self.assertEqual(t.loc["bmi", "source_field"], "")

    def test_ethnicity_substitute_field_is_partial(self):
        ds = make_ds(nationality=[None] * N, ethnicity=["Emirati"] * 24 + [None] * 26)
        t = by_var(framework.match_table({"c1": ds}, {"c1": FULL}))
        r = t.loc["ethnicity"]
        self.assertEqual((r["status"], r["route"], r["patients_with_value"]), ("Partial", "substitute", 24))
        self.assertIn("requested nationality not delivered", r["reason"])

    def test_ethnicity_absent_when_neither_field_has_values(self):
        ds = make_ds(nationality=["Not recorded"] * N)           # "not recorded" is not a value
        r = by_var(framework.match_table({"c1": ds}, {"c1": FULL})).loc["ethnicity"]
        self.assertEqual((r["status"], r["patients_with_value"], r["route"]), ("Absent", 0, "-"))

    def test_ethnicity_source_param_flips_the_requested_field(self):
        ds = make_ds(nationality=[None] * N, ethnicity=["Emirati"] * N)
        r = by_var(framework.match_table({"c1": ds}, {"c1": FULL}, {**PARAMS, "ethnicity_source": "ethnicity"}))
        self.assertEqual(r.loc["ethnicity", "status"], "Match")

    def test_drug_rows_derived_make_hypertension_partial(self):
        facts = {**FULL, "medications": {"requested_system": "ATC", "rows": 100, "as_requested_rows": 0}}
        r = by_var(framework.match_table({"c1": make_ds()}, {"c1": facts})).loc["hypertension"]
        self.assertEqual((r["status"], r["route"]), ("Partial", "derived"))
        self.assertIn("100% of the rows not in the requested system (ATC)", r["reason"])
        facts["medications"]["as_requested_rows"] = 97           # 3% derived ≤ the 5% tolerance
        self.assertEqual(by_var(framework.match_table({"c1": make_ds()}, {"c1": facts})).loc["hypertension", "status"],
                         "Match")

    def test_half_of_treated_hypertension_is_partial(self):
        r = by_var(framework.match_table({"c1": make_ds(htn_med=False)}, {"c1": FULL})).loc["hypertension"]
        self.assertEqual(r["status"], "Partial")
        self.assertIn("no antihypertensive drug arrived", r["reason"])
        r = by_var(framework.match_table({"c1": make_ds(htn_dx=False)}, {"c1": FULL})).loc["hypertension"]
        self.assertIn("no hypertension diagnosis arrived", r["reason"])
        r = by_var(framework.match_table({"c1": make_ds(htn_dx=False, htn_med=False)}, {"c1": FULL})).loc["hypertension"]
        self.assertEqual(r["status"], "Absent")

    def test_smoking_level_missing_is_partial(self):
        r = by_var(framework.match_table({"c1": make_ds()}, {"c1": FULL})).loc["smoking"]    # no "heavy" smoker
        self.assertEqual(r["status"], "Partial")
        self.assertIn("heavy", r["reason"])
        self.assertNotIn("never", r["reason"])
        ds = make_ds(smoking=["never"] * 20 + ["ex"] * 30)      # light / moderate / heavy each under 10 patients
        self.assertIn("light, moderate, heavy", by_var(framework.match_table({"c1": ds}, {"c1": FULL})).loc["smoking", "reason"])

    def test_family_history_recognised_from_text_is_partial(self):
        facts = {**FULL, "family_history": {"requested_system": "ICD-10 / SNOMED code", "rows": 100,
                                            "as_requested_rows": 62}}
        r = by_var(framework.match_table({"c1": make_ds()}, {"c1": facts})).loc["family_history"]
        self.assertEqual((r["status"], r["route"]), ("Partial", "derived"))
        self.assertIn("38% of the records", r["reason"])

    def test_values_for_few_patients_are_partial_only_for_recorded_variables(self):
        # family history for 30 of 50 patients = 60% → Match; with a record for 12 of 50 (24%) → Partial
        ds = make_ds()
        obs = ds["observations"]
        ds.tables["observations"] = obs[~(obs["concept"].eq("family_history_dm")
                                          & ~obs["patient_id"].isin([f"P{i:02d}" for i in range(12)]))]
        r = by_var(framework.match_table({"c1": ds}, {"c1": FULL}))
        self.assertEqual(r.loc["family_history", "status"], "Partial")
        self.assertIn("only 24.0% of patients (< 50%)", r.loc["family_history", "reason"])
        self.assertEqual(r.loc["cvd", "status"], "Match")        # CVD on 5 of 50 patients: a flag, not a record

    def test_cvd_absent_without_any_diagnosis(self):
        self.assertEqual(by_var(framework.match_table({"c1": make_ds(cvd=False)}, {"c1": FULL})).loc["cvd", "status"],
                         "Absent")


class TestOverallAndOutput(unittest.TestCase):
    def table(self, *statuses):
        return pd.DataFrame({"cohort": "c1", "variable": codelists.CORE_VARIABLES[:len(statuses)],
                             "status": list(statuses)})

    def test_overall(self):
        self.assertEqual(framework.overall(self.table("Match", "Match")), "Match")
        self.assertEqual(framework.overall(self.table("Match", "Partial")), "Partial")
        self.assertEqual(framework.overall(self.table("Match", "Absent")), "Partial")      # something arrived
        self.assertEqual(framework.overall(self.table("Absent", "Absent")), "No match")
        self.assertEqual(framework.overall(self.table()), "No match")
        self.assertEqual(framework.overall(self.table("Match", "Match"), ["antidiabetic"]), "Partial")   # code group missing

    def test_non_match_lists_variables_in_core_order(self):
        t = pd.DataFrame({"cohort": ["c1", "c2", "c1", "c2"], "variable": ["smoking", "smoking", "ethnicity", "sex"],
                          "status": ["Partial", "Match", "Absent", "Match"]})
        self.assertEqual(framework.non_match(t), {"ethnicity": {"c1": "Absent"}, "smoking": {"c1": "Partial"}})

    def test_small_counts_and_their_percentages_are_suppressed(self):
        ds = make_ds(nationality=[None] * N, ethnicity=["Emirati"] * 6 + [None] * 44)      # 6 patients
        out = framework.suppressed(framework.match_table({"c1": ds}, {"c1": FULL}))
        r = by_var(out).loc["ethnicity"]
        self.assertEqual((r["patients_with_value"], r["pct_patients"]), ("<10", "<10 patients"))
        self.assertEqual(by_var(out).loc["sex", "patients_with_value"], N)
        self.assertNotIn("15.0", by_var(out).loc["ethnicity", "reason"])         # no percentage of the small count


class TestDeliveryFacts(unittest.TestCase):
    def test_read_delivery(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            self.assertEqual(framework.read_delivery(base, "nabidh", "c1"), {})          # no ingest.json
            c = schema.cohort_dir(base, "nabidh", "c1")
            c.mkdir(parents=True)
            (c / "ingest.json").write_text(json.dumps({"ingest_version": "1.4.1", "delivery": FULL}), encoding="utf-8")
            self.assertEqual(framework.read_delivery(base, "nabidh", "c1"), FULL)
            (c / "ingest.json").write_text("{not json", encoding="utf-8")
            self.assertEqual(framework.read_delivery(base, "nabidh", "c1"), {})

    def test_adapter_facts_from_value_counts(self):
        vc = [{"source": "medications", "field": "drug → ATC method", "value": v, "n_rows": n}
              for v, n in [("ATC code", 10), ("DDC code", 70), ("name: trade name", 20)]]
        vc += [{"source": "family_history", "field": "diabetes recognised by", "value": v, "n_rows": n}
               for v, n in [("SNOMED code", 55), ("ICD-10 code", 5), ("text only", 40)]]
        f = nabidh.delivery_facts(vc)
        self.assertEqual(f["medications"], {"requested_system": "ATC", "rows": 100, "as_requested_rows": 10})
        self.assertEqual(f["family_history"], {"requested_system": "ICD-10 / SNOMED code", "rows": 100,
                                               "as_requested_rows": 60})
        self.assertEqual(nabidh.delivery_facts([]).keys(), {"fields"})                    # nothing counted → no shares

    def test_adapter_names_view_and_column_per_variable(self):
        f = nabidh.delivery_facts([])["fields"]
        self.assertEqual(f["sex"], "Patient.Gender_Code")
        self.assertEqual(f["ethnicity"], "Patient.Nationality | Patient.EthnicGroup_Description")
        self.assertEqual(f["hypertension"], "Diagnosis.Diagnosis_Code + Medication.DrugProduct_Code")
        self.assertIn("Observation.ObservationValue", f["bmi"])
        self.assertEqual(set(f), set(codelists.CORE_VARIABLES))

    def test_adapter_skips_a_variable_whose_source_is_not_configured(self):
        f = nabidh.delivery_facts([], {"patient_profile": nabidh.SOURCES["patient_profile"]})["fields"]
        self.assertEqual(set(f), {"sex", "age", "ethnicity"})


class TestKpiRow(unittest.TestCase):
    AUDIT = {"runs": 1, "closed": 1, "pct": 100.0, "open": []}

    def row(self, nb0):
        t = kpi.build(nb0, {}, {}, {}, self.AUDIT)
        return t.set_index("kpi").loc["Applicant Data Requirement Framework Match"]

    base = {"data_completeness_min_core8_pct": {"c1": 0.0}, "data_completeness_weakest": {"c1": "ethnicity"},
            "framework_match": True, "framework_missing_groups": []}

    def test_partial_is_its_own_status(self):
        r = self.row({**self.base, "framework_status": "Partial",
                      "framework_variables": {"ethnicity": {"c1": "Partial", "c2": "Partial"},
                                              "hypertension": {"c1": "Partial"}}})
        self.assertEqual(r["actual"], "Partial: ethnicity, hypertension")
        self.assertEqual(r["met"], "Partial")
        self.assertIn("ethnicity: C1 Partial, C2 Partial", r["notes"])
        self.assertIn("hypertension: C1 Partial", r["notes"])
        self.assertIn("not counted as Met or Not Met", r["notes"])

    def test_match_and_no_match(self):
        r = self.row({**self.base, "framework_status": "Match", "framework_variables": {}})
        self.assertEqual((r["actual"], r["met"]), ("Match", "Met"))
        r = self.row({**self.base, "framework_status": "No match", "framework_match": False,
                      "framework_variables": {"sex": {"c1": "Absent"}}, "framework_missing_groups": ["t2d"]})
        self.assertEqual((r["actual"], r["met"]), ("No match: sex", "Not Met"))
        self.assertIn("requested code groups not received: t2d", r["notes"])

    def test_old_nb0_without_status_keeps_the_code_group_result(self):
        r = self.row({**self.base})
        self.assertEqual((r["actual"], r["met"]), ("Match", "Met"))
        r = self.row({**self.base, "framework_match": False, "framework_missing_groups": ["antidiabetic"]})
        self.assertEqual((r["actual"], r["met"]), ("Missing: antidiabetic", "Not Met"))

    def test_partial_is_not_evaluated_in_the_graduation_rate(self):
        t = kpi.build({**self.base, "framework_status": "Partial", "framework_variables": {"sex": {"c1": "Partial"}}},
                      {}, {}, {}, self.AUDIT)
        self.assertEqual(kpi.graduation(t)["non_critical_evaluable"], 1)     # only Data Completeness (Not Met)


if __name__ == "__main__":
    unittest.main()
