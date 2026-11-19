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
from sandbox.io import schema  # noqa: E402
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
        self.assertEqual(self.rep["sources"]["lab_results"]["status"], "absent (optional)")
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

    def test_smoking_intensity_values(self):
        """NABIDH SocialHabitQty (2026-11-19): yoğunluk değerleri; 'other' eşlenmez (eksik, D7)."""
        vals = {"A1": "Low", "A2": "medium", "A3": "HIGH", "A4": "occasional"}
        rows = [f"{p},Smoking,{v},2019-01-01" for p, v in vals.items()]
        rows += ["A1,Smoking,rare,2019-02-01", "A2,Smoking,other,2019-02-01"]
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_raw(d, social_rows=rows)
            ds, _ = nabidh.load(d, "c1")
        sm = ds["observations"][ds["observations"]["concept"] == "smoking_status"].sort_values(["patient_id", "date"])
        self.assertEqual(list(zip(sm["patient_id"], sm["value"])),
                         [("A1", "light"), ("A1", "light"), ("A2", "moderate"), ("A2", "unmapped:other"),
                          ("A3", "heavy"), ("A4", "light")])
        self.assertEqual(nabidh.FH_RELATION_DEGREE["1st degree relative"], "first")

    def test_family_history_text(self):
        """FamilyHistory'de durum sütunu yok: olumsuzlama ve akraba derecesi açıklama metninden (2026-11-19)."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_raw(d)
            _csv(d, "family_history.csv", "Patient,Diagnosis_Code,Diagnosis_Description,FamilyMember_Description,EnteredOn", [
                "A1,44054006,No History Of Diabetes mellitus type 2 (disorder),Father,2020-01-01",
                "A2,88750,Maternal aunt and uncle have Diabetes mellitus,Parent,2020-01-01",
                "A3,Diabetes,Diabetes,Mother,",                       # kod sütununda metin, tarih yok
                "A4,2,DIABETIC,Father,2020-01-01",
                "A4,73211009,Diabetes mellitus (disorder),Grandmother and mother,2020-01-01",
            ])
            ds, rep = nabidh.load(d, "c1")
        fh = ds["observations"][ds["observations"]["concept"] == "family_history_dm"]
        self.assertEqual(list(zip(fh["patient_id"], fh["value"])),
                         [("A1", "negative"), ("A2", "positive_non_first_degree"), ("A3", "positive"),
                          ("A4", "positive"), ("A4", "positive")])               # metinde anne de var → birinci
        vc = pd.DataFrame(rep["value_counts"])
        self.assertEqual(set(vc.loc[vc["field"] == "condition_text negated → negative", "value"]),
                         {"No History Of Diabetes mellitus type 2 (disorder)"})

        # D27 (2026-11-19): aile öyküsü var / yok — tarihsiz ve referans sonrası kayıt da sayılır
        ref = pd.Series(pd.Timestamp("2019-12-31"), index=["A1", "A2", "A3", "A4"])
        s = phenotype.core_snapshot(ds, ref, None)
        self.assertEqual(list(s["family_history"]), [False, False, True, True])
        self.assertEqual(list(s["family_history_recorded"]), [True, True, True, True])
        old = phenotype.core_snapshot(ds, ref, None, dict(PARAMS, family_history_any_date=False))
        self.assertEqual(list(old["family_history_recorded"]), [False, False, False, False])
        v = schema.validate(ds).set_index("check")
        self.assertEqual(v.loc["family history without date (date not used, D27)", "n_affected"], 1)
        obs_date = v[(v["table"] == "observations")].loc["missing required date"]
        self.assertEqual((obs_date["severity"], obs_date["n_affected"]), ("INFO", 0))

    def test_family_history_code_first(self):
        """NABIDH C1 FamilyHistory.Diagnosis_Code (2026-11-19): SNOMED, ICD-10, kod sütununda metin, yerel numara.
        Önce kod, sonra metin; prediyabet diyabet aile öyküsü değil."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            write_raw(d)
            _csv(d, "family_history.csv", "Patient,Diagnosis_Code,Diagnosis_Description,FamilyMember_Description,EnteredOn", [
                "A1,Z83.3,Family history of diabetes mellitus,Mother,",
                "A1,73211009,Diabetes mellitus (disorder),Father,",
                "A2,DIABETES,DIABETES,Mother,",
                "A2,60376773,Diabetes,Father,",
                "A3,DM,DM,Sister,",
                "A3,714628002,Prediabetes,Mother,",
                "A4,R73.03,Pre-diabetes,Father,",
                "A4,5,Hypertension,Father,",
                "A4,2,Non-diabetic,Mother,",
            ])
            ds, rep = nabidh.load(d, "c1")
        fh = ds["observations"][ds["observations"]["concept"] == "family_history_dm"]
        self.assertEqual(list(zip(fh["patient_id"], fh["value"])),
                         [("A1", "positive"), ("A1", "positive"), ("A2", "positive"), ("A2", "positive"),
                          ("A3", "positive"), ("A4", "negative")])
        vc = pd.DataFrame(rep["value_counts"])
        by = vc[vc["field"] == "diabetes recognised by"].set_index("value")["n_rows"].to_dict()
        self.assertEqual(by, {"ICD-10 code": 1, "SNOMED code": 1, "text only": 4})
        pre = vc[vc["field"].str.endswith("(prediabetes, dropped)")]
        self.assertEqual(int(pre["n_rows"].sum()), 2)
        non = vc[vc["field"].str.endswith("(non-diabetes, dropped)")]
        self.assertEqual(list(non["value"]), ["5 | Hypertension"])

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


class TestLabResults(unittest.TestCase):
    """LabResultItem view'ı (C1 DDL, 2026-11-19): lab'lar birimiyle burada; Observation'da lab kodu yok."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        write_raw(d)
        hba1c = [f"P{i},Encounter{i},2021-0{1 + i % 9}-01,{5.0 + 0.2 * i:.1f},%,4548-4,HbA1c" for i in range(12)]
        _csv(d, "lab_results.csv", "Patient,Encounter,ResultDate,ResultValue,ResultValueUnits,TestItemCode_Code,"
                                   "TestItemCode_Description", hba1c + [
            "A3,E1,2020-02-01,42,mmol/mol,59261-8,HbA1c IFCC",          # IFCC → % (6,0)
            "A2,E2,2020-02-01,6.1,mmol/L,1558-6,Glucose fasting",       # mmol/L → mg/dL (109,9)
            "A2,E2,2020-02-01,190,mg/dL,2093-3,Cholesterol",            # çalışma lab'ı değil → düşer
            "A1,E3,2021-04-01,6.9,%,LOC-77,Glycated haemoglobin",       # yerel kodlu HbA1c → düşer, ayrı listede
            "A4,E4,2021-04-01,<2.8,,1558-6,FBS",                        # sayı değil, birim yok
            "A1,E5,2021-05-01,140,mg/dL,4548-4,EAG (ESTIMATED AVERAGE GLUCOSE)",   # HbA1c kodu, eAG → düşer
            "A2,E6,2021-05-01,180,mg/dL,1558-6,BLOOD SUGAR -RBS",       # açlık kodu, rastgele → düşer
            "P1,E7,2021-05-01,150,mg/dL,1521-4,GLUCOSE POST PRANDIAL (PPBS)",      # tutulur (not: OGTT değil)
            "A4,E8,2021-06-01,48,,4548-4,HbA1c",                        # birimsiz, mmol/mol gibi → aralık dışı, tutulur
        ])
        cls.ds, cls.rep = nabidh.load(d, "c1")
        cls.vc = pd.DataFrame(cls.rep["value_counts"])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def field(self, name):
        x = self.vc[(self.vc["source"] == "lab_results") & (self.vc["field"] == name)]
        return x.set_index("value")["n_rows"].to_dict()

    def test_study_labs_kept_with_unit(self):
        labs = self.ds["labs"]
        lab = labs[labs["patient_id"].isin(["A2", "A3", "A4"]) & labs["unit"].notna()].set_index("patient_id")
        self.assertEqual(lab.loc["A3", ["loinc", "unit"]].tolist(), ["59261-8", "mmol/mol"])
        self.assertEqual(lab.loc["A2", ["loinc", "unit"]].tolist(), ["1558-6", "mmol/L"])
        self.assertEqual(self.rep["sources"]["lab_results"]["rows_out"], {"labs": 17})
        self.assertNotIn("2093-3", set(labs["loinc"]))
        self.assertNotIn("LOC-77", set(labs["loinc"]))
        self.assertFalse(self.ds["observations"]["concept"].str.contains("2093-3|LOC-77").any())   # gözlem değil

    def test_units_converted_in_phenotype(self):
        g = phenotype.glycaemic_events(self.ds).set_index(["patient_id", "date"])
        self.assertAlmostEqual(g.loc[("A3", pd.Timestamp("2020-02-01")), "value"], 42 / 10.929 + 2.15)
        a2 = g.loc[("A2", pd.Timestamp("2020-02-01"))]
        self.assertAlmostEqual(a2["value"], 6.1 * 18.016)
        self.assertEqual(a2["status"], "pre")

    def test_report_lists_codes_and_dropped_tests(self):
        self.assertEqual(self.field("study lab: code | unit | name")["4548-4 | % | HbA1c"], 12)
        self.assertIn("LOC-77 | % | Glycated haemoglobin",
                      self.field("glycaemic-looking tests (dropped): code | unit | name"))
        self.assertEqual(list(self.field("other tests (dropped): code | unit | name")),
                         ["2093-3 | mg/dL | Cholesterol"])
        self.assertEqual(self.field("rows dropped: not a study lab"), {"<n rows>": 2})
        self.assertEqual(set(self.field("study code, other test by name (dropped): code | unit | name")),
                         {"4548-4 | mg/dL | EAG (ESTIMATED AVERAGE GLUCOSE)", "1558-6 | mg/dL | BLOOD SUGAR -RBS"})
        self.assertEqual(self.field("rows dropped: study code, other test by name"), {"<n rows>": 2})
        g = phenotype.glycaemic_events(self.ds)
        self.assertFalse((g["kind"].eq("hba1c") & g["value"].eq(140)).any())   # eAG HbA1c sanılmadı
        self.assertEqual(self.field("lab value non-numeric (raw)"), {"<2.8": 1})

    def test_value_outside_plausible_range_is_reported_and_kept(self):
        self.assertEqual(self.field("value outside plausible range"), {"hba1c | <no unit> : outside 3–20 % (kept)": 1})
        labs = self.ds["labs"]
        self.assertTrue((labs["patient_id"].eq("A4") & labs["value"].eq(48)).any())    # eleme kararı yok, K11
        rng = nabidh.lab_range_class(pd.Series(["hba1c", "hba1c", "hba1c_ifcc", "fpg", "ogtt_2h"]),
                                     pd.Series(["%", "mmol/mol", None, "mmol/L", None]))
        self.assertEqual(list(rng), ["hba1c %", "hba1c mmol/mol", "hba1c mmol/mol", "glucose mmol/L", "glucose mg/dL"])

    def test_value_distribution_only_for_ten_patients(self):
        stats = self.field("value by kind | unit")
        self.assertIn("hba1c | % : 12 patients, p5 5.11 / median 6.1 / p95 7.09", stats)
        small = [k for k in stats if k.startswith(("hba1c_ifcc", "fpg"))]
        self.assertEqual(len(small), 3)                          # mmol/mol, mmol/L, <no unit>
        self.assertTrue(all("no distribution" in k for k in small))


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
