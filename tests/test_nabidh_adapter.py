"""NABIDH adapter'ı (teslim yapısı: Patient, tanı, Observation, SocialHistory, FamilyHistory, Medication)
ve uyruk → etnik grup eşlemesi için testler. Ham dosyalar geçici klasörde elle üretilir."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from sandbox import codelists, phenotype  # noqa: E402
from sandbox.config import PARAMS  # noqa: E402
from sandbox.io.adapters import nabidh  # noqa: E402
from sandbox.scores import lrs, qdiabetes2018a as qd  # noqa: E402


def _csv(d: Path, name: str, header: str, rows: list[str], encoding="utf-8"):
    (d / name).write_text("\n".join([header, *rows]) + "\n", encoding=encoding)


def write_raw(d: Path, social_rows=None, dob="1970-01-01"):
    # BOM'lu dosya (Excel çıktısı) + karışık cinsiyet yazımı
    _csv(d, "patients.csv", "patient_id,sex,date_of_birth,nationality,ethnicity,facility_id", [
        f"A1,M,{dob},United Arab Emirates,,F1",
        "A2,female,1980-05-05,IND,,F1",
        "A3,F,1975-02-02,Iran,,F2",
        "A4,MALE,1965-03-03,,,F2",
    ], encoding="utf-8-sig")
    _csv(d, "diagnoses.csv", "patient_id,code_system,code,description,diagnosis_date", [
        "A1,I10,E11.9,T2D,2021-01-01",           # HL7 'I10' = ICD-10
        "A2,ICD10,I10,HTN,2019-01-01",
        "A3,ICD-10,R73.03,Prediabetes,2020-01-01",
        "A4,ICD-10,E11.9,T2D,not-a-date",
    ])
    _csv(d, "observations.csv", "patient_id,code_system,loinc,name,value,unit,date", [
        "A1,LN,4548-4,HbA1c,6.8,%,2021-01-01",
        "A2,LN,1558-6,FPG,<5.0,mmol/L,2020-01-01",
        "A1,LN,39156-5,BMI,31.2,kg/m2,2020-06-01",
        "A2,LN,8302-2,Height,160,cm,2015-01-01",
        "A2,LN,3141-9,Weight,64,kg,2020-01-01",
        "A3,LN,9999-9,Mystery,1,,2020-01-01",
    ])
    _csv(d, "social_history.csv", "patient_id,item,value,code,date", social_rows or [
        "A1,Smoking,Never smoker,,2018-01-01",
        "A1,Smoking,unknown,,2020-01-01",            # bilgisiz → önceki 'never' korunur
        "A2,Smoking,Current every day smoker,,2019-01-01",
        "A3,Smoking,,8517006,2019-01-01",            # yalnız SNOMED kod → ex
        "A4,Smoking,weird value,,2019-01-01",        # eşlenemez
    ])
    _csv(d, "family_history.csv", "patient_id,relation,condition,status,date", [
        "A1,Mother,Diabetes mellitus type 2,Yes,2018-01-01",
        "A1,Father,Hypertension,Yes,2018-01-01",     # diyabet değil → atılır
        "A2,Uncle,Diabetes,Yes,2018-01-01",          # ikinci derece → pozitif sayılmaz, kayıt var
        "A3,,E11,No,2018-01-01",                     # negatif kayıt
        "A4,Sister,Diabetes,maybe,2018-01-01",       # eşlenemeyen durum
    ])
    _csv(d, "medications.csv", "patient_id,atc_code,drug_name,prescription_date,route", [
        "A2,c09aa02,Enalapril,2019-02-01,Oral",
        "A1,Metformin,Metformin,2021-02-01,Oral",    # ATC değil → raporlanır
    ])


class TestAdapter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        write_raw(d)
        cls.ds, cls.rep = nabidh.load(d, "c1")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_patients(self):
        p = self.ds["patients"].set_index("patient_id")
        self.assertEqual(list(p["sex"]), ["Male", "Female", "Female", "Male"])
        self.assertEqual(p.loc["A2", "nationality"], "IND")

    def test_code_system_normalised(self):
        c = self.ds["conditions"]
        self.assertTrue((c["code_system"] == "ICD-10").all())
        self.assertTrue(codelists.match_dx(c, "t2d").any())

    def test_measurements_split(self):
        self.assertEqual(sorted(self.ds["labs"]["loinc"]), ["1558-6", "4548-4"])
        self.assertTrue(np.isnan(self.ds["labs"].set_index("loinc").loc["1558-6", "value"]))   # "<5.0"
        concepts = set(self.ds["observations"]["concept"])
        self.assertTrue({"bmi", "height_cm", "weight_kg", "unmapped:9999-9"} <= concepts)

    def test_smoking_values(self):
        o = self.ds["observations"]
        sm = o[o["concept"] == "smoking_status"].set_index(["patient_id", "date"])["value"]
        self.assertEqual(sm.loc[("A1", pd.Timestamp("2018-01-01"))], "never")
        self.assertEqual(sm.loc[("A1", pd.Timestamp("2020-01-01"))], "unknown")
        self.assertEqual(sm.loc[("A2", pd.Timestamp("2019-01-01"))], "current")
        self.assertEqual(sm.loc[("A3", pd.Timestamp("2019-01-01"))], "ex")
        self.assertEqual(sm.loc[("A4", pd.Timestamp("2019-01-01"))], "unmapped:weird value")

    def test_family_history_values(self):
        o = self.ds["observations"]
        fh = o[o["concept"] == "family_history_dm"].groupby("patient_id")["value"].apply(sorted).to_dict()
        self.assertEqual(fh, {"A1": ["positive"], "A2": ["positive_non_first_degree"], "A3": ["negative"],
                              "A4": ["unmapped:maybe"]})

    def test_medications_uppercased(self):
        self.assertIn("C09AA02", set(self.ds["medications"]["atc_code"]))

    def test_report(self):
        self.assertEqual(self.rep["sources"]["diagnoses"]["unparseable_date"], 1)
        self.assertEqual(self.rep["sources"]["encounters"]["status"], "absent (optional)")
        vc = pd.DataFrame(self.rep["value_counts"])
        self.assertTrue(vc["value"].str.contains("unmapped:weird value").any())
        self.assertIn("METFORMIN", set(vc.loc[vc["field"] == "atc_code not ATC-like", "value"]))

    def test_snapshot_uses_family_and_social_history(self):
        ref = pd.Series(pd.Timestamp("2022-12-31"), index=["A1", "A2", "A3", "A4"])
        s = phenotype.core_snapshot(self.ds, ref, None, dict(PARAMS, c1_require_fh_record=True))
        self.assertEqual(s.loc["A1", "smoking_raw"], "never")       # sonraki 'unknown' ezmez
        self.assertEqual(s.loc["A2", "smoking_raw"], "current")
        self.assertEqual(s.loc["A3", "smoking_raw"], "ex")
        self.assertFalse(s.loc["A4", "ok_smoking"])                 # eşlenemeyen değer = eksik
        self.assertEqual(list(s["family_history"]), [True, False, False, False])
        self.assertEqual(list(s["family_history_recorded"]), [True, True, True, False])
        self.assertEqual(list(s["ok_family_history"]), [True, True, True, False])
        self.assertEqual(s.loc["A2", "bmi_source"], "height_weight")
        self.assertEqual(list(s["ethnicity"].fillna("<NA>")),
                         ["Emirati", "Indian", codelists.UNMAPPED_NATIONALITY, "<NA>"])


class TestAdapterOptions(unittest.TestCase):
    def test_date_format_day_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_raw(d, dob="03/04/1970")
            src = copy.deepcopy(nabidh.SOURCES)
            src["patient_profile"]["date_format"] = "%d/%m/%Y"
            ds, rep = nabidh.load(d, "c1", src)
        dob = ds["patients"].set_index("patient_id").loc["A1", "date_of_birth"]
        self.assertEqual(dob, pd.Timestamp("1970-04-03"))

    def test_missing_required_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_raw(d)
            src = copy.deepcopy(nabidh.SOURCES)
            src["diagnoses"]["columns"]["code"] = "icd_code"
            with self.assertRaises(KeyError) as cm:
                nabidh.load(d, "c1", src)
        self.assertIn("icd_code", str(cm.exception))

    def test_social_history_needs_filter_when_mixed(self):
        rows = ["A1,Smoking,Never smoker,,2018-01-01", "A1,Alcohol,Yes,,2018-01-01"]
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_raw(d, social_rows=rows)
            with self.assertRaises(ValueError):
                nabidh.load(d, "c1")
            src = copy.deepcopy(nabidh.SOURCES)
            src["social_history"]["filter"] = {"item": ["smoking"]}
            ds, rep = nabidh.load(d, "c1", src)
        sm = ds["observations"][ds["observations"]["concept"] == "smoking_status"]
        self.assertEqual(list(sm["value"]), ["never"])
        self.assertEqual(rep["sources"]["social_history"]["filtered_out_by_item"], 1)


class TestNationality(unittest.TestCase):
    def test_variants(self):
        raw = pd.Series(["United Arab Emirates", "ARE", "ae", " Saudi ", "IND", "Pakistani", "Iran", None])
        g = codelists.ethnic_group(raw, "nationality")
        self.assertEqual(list(g.fillna("<NA>")), [
            "Emirati", "Emirati", "Emirati", "Gulf Arab (non-Emirati)", "Indian", "Pakistani",
            codelists.UNMAPPED_NATIONALITY, "<NA>"])

    def test_ethnicity_source_passthrough(self):
        raw = pd.Series(["Emirati", "Western"])
        self.assertEqual(list(codelists.ethnic_group(raw, "ethnicity")), ["Emirati", "Western"])

    def test_groups_map_to_scores(self):
        g = codelists.ethnic_group(pd.Series(["UAE", "India", "Iran", "UK", None]), "nationality")
        self.assertEqual(list(codelists.map_ethnicity_qdiabetes(g)),
                         ["Other", "Indian", "Other", "WhiteNA", "WhiteNA"])
        snap = pd.DataFrame({"sex": "Male", "age": 45, "ethnicity": g, "family_history": False,
                             "waist_cm": 95, "bmi": 27, "htn_lrs": False})
        pts = lrs.score(snap)["lrs_ethnicity"]
        self.assertEqual(list(pts.fillna(-1)), [6, 6, 6, 0, -1])     # kayıtsız → LRS hesaplanmaz

    def test_qd_unchanged_for_group_labels(self):
        # Aynı etnik grup etiketi → aynı QDiabetes riski (uyruk yolu skoru değiştirmez)
        base = dict(sex="Female", age=50, bmi=30, smoking_cat=0.0, smoking_raw="never", family_history=False,
                    cvd=False, htn_treated_qd=False, corticosteroid=False, apsy=False, statin=False, psy=False,
                    learn=False, gdm=False, pcos=False)
        a = qd.score(pd.DataFrame([{**base, "ethnicity": "Indian"}]))["qd_lp"].iloc[0]
        b = qd.score(pd.DataFrame([{**base, "ethnicity": codelists.ethnic_group(pd.Series(["India"]),
                                                                                   "nationality").iloc[0]}]))["qd_lp"].iloc[0]
        self.assertAlmostEqual(a, b, places=12)


if __name__ == "__main__":
    unittest.main()
