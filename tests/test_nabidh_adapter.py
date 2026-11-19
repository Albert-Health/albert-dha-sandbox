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


def write_raw(d: Path, social_rows=None, diag_date="2021-01-01", social_item="SocialHabitCategory_Code",
              drug_code=True):
    """HSAA view'larının biçimi (enclave, 2026-11-18): Patient.ID = diğer view'larda Patient; yaş var, doğum
    tarihi yok. social_item / drug_code: C2'deki farklar (kategori açıklaması, ilaç kodu yok)."""
    # BOM'lu dosya (Excel çıktısı) + karışık cinsiyet yazımı
    _csv(d, "patients.csv", "ID,Age,Gender_Code,EthnicGroup_Description,Nationality", [
        "A1,56,M,,United Arab Emirates",
        "A2,46,female,,IND",
        "A3,51,F,,Iran",
        "A4,abc,MALE,,",                             # yaş sayı değil → doğum tarihi yok
    ], encoding="utf-8-sig")
    _csv(d, "diagnoses.csv", "Patient,Diagnosis_Code,Diagnosis_Description,DiagnosisDate", [
        f"A1,E11.9,T2D,{diag_date}",
        "A2,I10,HTN,2019-01-01",
        "A3,R73.03,Prediabetes,2020-01-01",
        "A4,E11.9,T2D,not-a-date",
    ])
    _csv(d, "observations.csv", "Patient,ObservationCode_Code,ObservationCode_Description,ObservationValue,"
                                "ObservationDate", [
        "A1,4548-4,HbA1c,6.8,2021-01-01",
        "A2,1558-6,FPG,<5.0,2020-01-01",
        "A1,39156-5,BMI,31.2,2020-06-01",
        "A2,8302-2,Height,160,2015-01-01",
        "A2,3141-9,Weight,64,2020-01-01",
        "A3,9999-9,Mystery,1,2020-01-01",
    ])
    _csv(d, "social_history.csv", f"Patient,{social_item},SocialHabitQty_Description,EnteredOn", social_rows or [
        "A1,Smoking,Never smoker,2018-01-01",
        "A1,Smoking,unknown,2020-01-01",             # bilgisiz → önceki 'never' korunur
        "A2,Smoking,Current every day smoker,2019-01-01",
        "A3,Smoking,Ex-smoker,2019-01-01",
        "A4,Smoking,weird value,2019-01-01",         # eşlenemez
    ])
    _csv(d, "family_history.csv", "Patient,Diagnosis_Code,Diagnosis_Description,FamilyMember_Description,EnteredOn", [
        "A1,E11,Diabetes mellitus type 2,Mother,2018-01-01",
        "A1,I10,Hypertension,Father,2018-01-01",     # diyabet değil → atılır
        "A2,,Diabetes,Uncle,2018-01-01",             # yalnız açıklama; ikinci derece → pozitif sayılmaz
        "A3,E11.9,,,2018-01-01",                     # yalnız kod; akrabalık yok → birinci derece sayılır
    ])
    if drug_code:
        _csv(d, "medications.csv", "Patient,DrugProduct_Code,DrugProduct_Description,FromTime,Route_Description", [
            "A2,c09aa02,Enalapril,2019-02-01,Oral",                  # ATC biçiminde (küçük harf)
            "A1,0321-164101-0391,GLUCOPHAGE,2021-02-01,Oral",         # DDC ürün kodu → metformin
            "A3,00136271010391,IMPRIDA 5MG/160MG,2020-03-01,Oral",    # DDC (tiresiz), kombinasyon → 2 satır
            "A3,0169-120501-0371,APIMOL,2020-03-01,Ocular",           # timolol göz damlası → sınıf yok
            "A2,0006-106607-1161,PANADOL,2019-02-01,Oral",            # parasetamol → çalışma sınıfı değil
            "A1,Metformin,Metformin,2021-02-01,Oral",                 # kod tanınmaz → addan
            "A4,XYZ-1,Unknown tablet,2021-02-01,Oral",                # ne kod ne ad → raporlanır, düşer
        ])
    else:
        _csv(d, "medications.csv", "Patient,DrugProduct_Description,FromTime,Route_Description", [
            "A2,Enalapril,2019-02-01,Oral",                          # etken madde adı
            "A1,GLUCOPHAGE XR 500MG,2021-02-01,Oral",                # DDC ticari adı (marka kökü)
            "A3,BETNOVATE CREAM,2020-01-01,Topical",                 # yerel steroid → sınıf yok
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

    def test_date_of_birth_from_age(self):
        p = self.ds["patients"].set_index("patient_id")["date_of_birth"]
        ref = pd.Timestamp(nabidh.AGE_REFERENCE_DATE)
        self.assertEqual(p["A1"], (ref - pd.Timedelta(days=56.5 * 365.25)).normalize())
        age_at_ref = (ref - p["A1"]).days / 365.25
        self.assertTrue(56 <= age_at_ref < 57)
        self.assertTrue(pd.isna(p["A4"]))                         # "abc" → NaT, raporlanır
        vc = pd.DataFrame(self.rep["value_counts"])
        derived = vc[vc["field"] == "date_of_birth"]
        self.assertEqual(int(derived["n_rows"].iloc[0]), 3)
        self.assertIn("abc", set(vc.loc[vc["field"].str.startswith("age not usable"), "value"]))

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
        self.assertEqual(fh, {"A1": ["positive"], "A2": ["positive_non_first_degree"], "A3": ["positive"]})

    def test_medications_atc_ddc_and_name(self):
        m = self.ds["medications"]
        self.assertEqual(sorted(zip(m["patient_id"], m["atc_code"])),
                         [("A1", "A10BA02"), ("A1", "A10BA02"), ("A2", "C09AA02"), ("A3", "C08CA01"),
                          ("A3", "C09CA03")])

    def test_report(self):
        self.assertEqual(self.rep["sources"]["diagnoses"]["unparseable_date"], 1)
        self.assertEqual(self.rep["sources"]["encounters"]["status"], "absent (optional)")
        vc = pd.DataFrame(self.rep["value_counts"])
        self.assertTrue(vc["value"].str.contains("unmapped:weird value").any())
        self.assertEqual(set(vc.loc[vc["field"] == "drug code not ATC/DDC", "value"]), {"METFORMIN", "XYZ-1"})
        how = vc[vc["field"] == "drug → ATC method"].set_index("value")["n_rows"]
        self.assertEqual(how["DDC code"], 2)
        self.assertEqual(how["DDC: non-systemic route"], 1)
        self.assertEqual(how["DDC: not a study drug class"], 1)
        self.assertEqual(how["code not ATC/DDC → name: trade name + ingredient"], 1)
        dropped = vc.loc[vc["field"] == "rows dropped: no study drug class", "n_rows"]
        self.assertEqual(int(dropped.iloc[0]), 3)
        self.assertEqual(self.rep["sources"]["medications"]["rows_out"], {"medications": 5})

    def test_snapshot_uses_family_and_social_history(self):
        ref = pd.Series(pd.Timestamp("2022-12-31"), index=["A1", "A2", "A3", "A4"])
        s = phenotype.core_snapshot(self.ds, ref, None, dict(PARAMS, c1_require_fh_record=True))
        self.assertEqual(s.loc["A1", "smoking_raw"], "never")       # sonraki 'unknown' ezmez
        self.assertEqual(s.loc["A2", "smoking_raw"], "current")
        self.assertEqual(s.loc["A3", "smoking_raw"], "ex")
        self.assertFalse(s.loc["A4", "ok_smoking"])                 # eşlenemeyen değer = eksik
        self.assertEqual(list(s["family_history"]), [True, False, True, False])
        self.assertEqual(list(s["family_history_recorded"]), [True, True, True, False])
        self.assertEqual(list(s["ok_family_history"]), [True, True, True, False])
        self.assertEqual(s.loc["A2", "bmi_source"], "height_weight")
        self.assertEqual(list(s["ethnicity"].fillna("<NA>")),
                         ["Emirati", "Indian", codelists.UNMAPPED_NATIONALITY, "<NA>"])


class TestAdapterOptions(unittest.TestCase):
    def test_date_format_day_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_raw(d, diag_date="03/04/2021")
            src = copy.deepcopy(nabidh.SOURCES)
            src["diagnoses"]["date_format"] = "%d/%m/%Y"
            ds, rep = nabidh.load(d, "c1", src)
        dx = ds["conditions"].set_index("patient_id").loc["A1", "date"]
        self.assertEqual(dx, pd.Timestamp("2021-04-03"))

    def test_birth_date_column_preferred_over_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_raw(d)
            pts = pd.read_csv(d / "patients.csv", dtype=str, encoding="utf-8-sig")
            pts["BirthDate"] = ["1970-01-01", "", "", ""]
            pts.to_csv(d / "patients.csv", index=False)
            ds, _ = nabidh.load(d, "c1")
        p = ds["patients"].set_index("patient_id")["date_of_birth"]
        self.assertEqual(p["A1"], pd.Timestamp("1970-01-01"))
        self.assertTrue(pd.notna(p["A2"]))                         # BirthDate boş → yaştan

    def test_c2_shape(self):
        """C2: sigara kategorisi açıklama sütununda, ilaç kodu yok. Eşleme yine çalışmalı."""
        rows = ["A1,Tobacco,Never smoker,2018-01-01", "A1,Alcohol,Yes,2018-01-01"]
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_raw(d, social_rows=rows, social_item="SocialHabitCategory_Description", drug_code=False)
            src = copy.deepcopy(nabidh.SOURCES)
            src["social_history"]["filter"] = {"item": ["tobacco"]}
            ds, rep = nabidh.load(d, "c2", src)
        sm = ds["observations"][ds["observations"]["concept"] == "smoking_status"]
        self.assertEqual(list(sm["value"]), ["never"])
        self.assertEqual(rep["sources"]["social_history"]["filtered_out_by_item"], 1)
        m = ds["medications"]                                       # kod yok → ilaç adından (DDC + etken madde)
        self.assertEqual(sorted(zip(m["patient_id"], m["atc_code"])), [("A1", "A10BA02"), ("A2", "C09AA02")])
        self.assertIn("atc_code", rep["sources"]["medications"]["absent_optional_columns"])
        vc = pd.DataFrame(rep["value_counts"])
        self.assertIn("C09AA02 ← Enalapril", set(vc.loc[vc["field"] == "ATC ← drug_name (name match)", "value"]))
        self.assertEqual(set(vc.loc[vc["field"] == "drug_name without study drug class", "value"]), {"BETNOVATE CREAM"})
        self.assertEqual(int(vc.loc[vc["field"] == "rows dropped: no study drug class", "n_rows"].iloc[0]), 1)

    def test_missing_required_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_raw(d)
            src = copy.deepcopy(nabidh.SOURCES)
            src["diagnoses"]["columns"]["code"] = ["icd_code", "dx_code"]
            with self.assertRaises(KeyError) as cm:
                nabidh.load(d, "c1", src)
        self.assertIn("icd_code | dx_code", str(cm.exception))

    def test_social_history_needs_filter_when_mixed(self):
        rows = ["A1,Smoking,Never smoker,2018-01-01", "A1,Alcohol,Yes,2018-01-01"]
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_raw(d, social_rows=rows)
            src = copy.deepcopy(nabidh.SOURCES)
            src["social_history"]["filter"] = None
            with self.assertRaises(ValueError):                    # filtre yok → hangi kalem sigara, bilinmez
                nabidh.load(d, "c1", src)
            src["social_history"]["filter"] = {"item": ["smoking"]}
            ds, rep = nabidh.load(d, "c1", src)
        sm = ds["observations"][ds["observations"]["concept"] == "smoking_status"]
        self.assertEqual(list(sm["value"]), ["never"])
        self.assertEqual(rep["sources"]["social_history"]["filtered_out_by_item"], 1)

    def test_social_history_c1_categories(self):
        """C1 kalemleri (enclave ingest, 2026-11-19): varsayılan filtre tütün kalemlerini birlikte alır."""
        rows = ["A1,Smoking,Never smoker,2018-01-01", "A2,Cigarettes,Current smoker,2019-01-01",
                "A3,\"Cigarettes,Cigars\",Ex-smoker,2019-01-01", "A4,Cigars,10 per day,2019-01-01",
                "A2,Other,Yes,2019-01-01", "A3,Unknown,Yes,2019-01-01", "A4,Beverages,Tea,2019-01-01"]
        rows += [f"A1,ALCOHOL,No,2018-01-{i:02d}" for i in range(1, 13)]           # 12 satır: etiket adı basılır
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_raw(d, social_rows=rows)
            ds, rep = nabidh.load(d, "c1")
        sm = ds["observations"][ds["observations"]["concept"] == "smoking_status"]
        self.assertEqual(dict(zip(sm["patient_id"], sm["value"])),
                         {"A1": "never", "A2": "current", "A3": "ex", "A4": "unmapped:10 per day"})
        info = rep["sources"]["social_history"]
        self.assertEqual(info["filtered_out_by_item"], 15)
        self.assertEqual(info["filtered_out_values_item"], "ALCOHOL (12), +3 etiket < 10 satır")
        vc = pd.DataFrame(rep["value_counts"])
        shown = set(vc.loc[vc["field"] == "value → canonical", "value"])
        self.assertIn("Cigars | 10 per day → unmapped:10 per day", shown)   # eşlenemeyen değerin kalemi görünür

    def test_filter_that_drops_everything_stops(self):
        """C2'de kalem adları farklıysa sigara sessizce boş kalmasın: ingest durur, kalemleri basar."""
        rows = [f"A{1 + i % 4},Tobacco use,Never,2018-01-{1 + i:02d}" for i in range(11)] + ["A1,Alcohol,No,2018-02-01"]
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_raw(d, social_rows=rows, social_item="SocialHabitCategory_Description")
            with self.assertRaises(ValueError) as cm:
                nabidh.load(d, "c2")
        msg = str(cm.exception)
        self.assertIn("bütün satırları eledi", msg)
        self.assertIn("Tobacco use (11)", msg)
        self.assertIn("+1 etiket < 10 satır", msg)                    # Alcohol: 1 satır, adı basılmaz


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
                             "waist_cm": 95, "bmi": 27, "htn_lrs": False, "htn_med": False})
        pts = lrs.score_assessment_2010(snap)["lrs_ethnicity"]
        self.assertEqual(list(pts.fillna(-1)), [6, 6, 6, 0, -1])     # kayıtsız → LRS hesaplanmaz
        bme = lrs.score(snap)["lrs_ethnicity"]                         # varsayılan LPRS: BME katsayısı
        self.assertEqual(list(bme.fillna(-1).round(7)), [0.7565977] * 3 + [0.0, -1])

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
