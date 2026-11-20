"""Faz 1 step 1d (codes) on the NABIDH adapter: drug code shapes seen in the real C1 / C2 Medication view (VM ingest
v1.2.1, 2026-11-19) and the ingest-block lists for DDC codes without a study drug class (i22). Hand-made rows; the DDC
codes are products in src/sandbox/reference/ddc.csv.gz."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import pandas as pd  # noqa: E402

import enclave  # noqa: E402
from sandbox import codelists  # noqa: E402
from sandbox.io.adapters import ddc, nabidh  # noqa: E402

PARACETAMOL = "0006-106607-1161"        # DDC product, not a study class
TIMOLOL_EYE = "0169-120501-0371"        # DDC product, study ingredient but ocular route


class TestCodeShapes(unittest.TestCase):
    def test_formats(self):
        f = ddc.code_format
        self.assertEqual(f("0005-379302-1171"), "DDC product code (9999-999999-9999)")
        self.assertEqual(f("00053793021171"), "DDC product code (9999-999999-9999)")
        self.assertEqual(f("164101-039"), "DDC scientific code (999999-999)")
        self.assertEqual(f("581303"), "6 digits (DDC scientific code stem)")
        self.assertEqual(f("VMP4763,750 MG,TI"), "VMP<id>,<dose>,<form> (no reference)")
        self.assertEqual(f("VMP42576,100 UNIT/ML (70-30),IO"), "VMP<id>,<dose>,<form> (no reference)")
        self.assertEqual(f("A10BA02"), "ATC")
        self.assertEqual(f("0000-000000-0000"), "placeholder (all zeros) → no code")
        self.assertEqual(f(None), "no code")
        self.assertEqual(f("  "), "no code")
        self.assertEqual(f("XYZ-1"), "other")

    def test_placeholder(self):
        self.assertTrue(ddc.is_placeholder("0000-000000-0000"))
        self.assertTrue(ddc.is_placeholder("00000000000000"))
        self.assertFalse(ddc.is_placeholder("0000-000000-0001"))
        self.assertFalse(ddc.is_placeholder(None))
        self.assertEqual(ddc.lookup_code("0000-000000-0000"), ("not a DDC code", []))

    def test_six_digit_stem(self):
        """The 6-digit codes of the C1 / C2 "drug code not ATC/DDC" list are DDC scientific code stems; their drug names
        in the same block (valsartan, Entresto, nebivolol, Xigduo XR, glimepiride) match the DDC products."""
        self.assertEqual(ddc.lookup_code("166101"), ("DDC scientific code stem", ["C09CA03"]))       # valsartan
        self.assertEqual(ddc.lookup_code("581303"), ("DDC scientific code stem", ["C09CA03"]))       # Entresto
        self.assertEqual(ddc.lookup_code("229701"), ("DDC scientific code stem", ["C07AB12"]))       # nebivolol
        self.assertEqual(ddc.lookup_code("585204"), ("DDC scientific code stem", ["A10BK01", "A10BA02"]))
        self.assertEqual(ddc.lookup_code("114201"), ("DDC scientific code stem", ["A10BB12"]))       # glimepiride
        self.assertEqual(ddc.lookup_code("106607"), ("DDC: not a study drug class", []))             # paracetamol
        # a stem with systemic and local forms (prednisolone tablets + enema) is not decided by the code
        self.assertEqual(ddc.lookup_code("119803"), ("not a DDC code", []))
        self.assertEqual(ddc.lookup_code("999999"), ("not a DDC code", []))
        self.assertEqual(ddc.lookup_code("12345"), ("not a DDC code", []))                           # 5 digits

    def test_code_info(self):
        self.assertEqual(ddc.code_info(PARACETAMOL), "PARACETAMOL | ORAL")
        self.assertEqual(ddc.code_info(TIMOLOL_EYE), "TIMOLOL | OCULAR")
        self.assertEqual(ddc.code_info("166101"), "VALSARTAN | ORAL")
        self.assertIsNone(ddc.code_info("VMP4763,750 MG,TI"))
        self.assertIsNone(ddc.code_info(None))


def _meds(rows):
    df = pd.DataFrame(rows, columns=["atc_code", "drug_name", "route"])
    df.insert(0, "patient_id", [f"P{i}" for i in range(len(df))])
    df["date"] = pd.Timestamp("2021-01-01")
    vc: list[dict] = []
    out = nabidh._h_medications(df, "medications", vc)["medications"]
    return out, pd.DataFrame(vc)


def _field(vc, field):
    return vc[vc["field"] == field].set_index("value")["n_rows"].to_dict()


class TestCodeNameClash(unittest.TestCase):
    """VM ingest 1.3.0 (2026-11-20): C1 and C2 each had 134 rows whose DDC code is a cholecalciferol product while the
    name is dapagliflozin + metformin (Xigduo XR 5/1000, three spellings). Mapping rule: a code outside every study
    class gives way to a name that is about a study drug."""
    CHOLECALCIFEROL = "1499-348905-1171"       # VITA-D 10000IU tablets (DDC)

    def test_name_leads_with_study_drug(self):
        f = ddc.name_leads_with_study_drug
        for n in ("DAPAGLIFLOZIN 5 MG-METFORMIN ER 1,000 MG TABLET", "DAPAGLIFLOZIN/METFORMIN 5 MG/1000 MG EXTENDED",
                  "DAPAGLIFLOZIN PROPANED 5 MG-METFORMIN ER 1,000", "XIGDUO XR 5/1000", "xigduo", "TAB CRESTOR 10 MG"):
            self.assertTrue(f(n), n)
        for n in ("VITAMIN D3 1000 IU (ON METFORMIN)", "PANADOL 500 MG, TAKES METFORMIN", "Insulin pen needles",
                  "500 MG", None, ""):
            self.assertFalse(f(n), n)

    def test_xigduo_with_a_cholecalciferol_code(self):
        self.assertEqual(ddc.lookup_code(self.CHOLECALCIFEROL), ("DDC: not a study drug class", []))
        r = nabidh._resolve_drug
        for n in ("DAPAGLIFLOZIN 5 MG-METFORMIN ER 1,000 MG TAB", "DAPAGLIFLOZIN/METFORMIN 5 MG/1000 MG EXTENDE",
                  "DAPAGLIFLOZIN PROPANED 5 MG-METFORMIN ER 1,0"):
            self.assertEqual(r(self.CHOLECALCIFEROL, n, None),
                             ("DDC: not a study drug class → name: ingredient", ["A10BK01", "A10BA02"]), n)
        self.assertEqual(r(self.CHOLECALCIFEROL, "VITAMIN D3 10000 IU", None), ("DDC: not a study drug class", []))
        self.assertEqual(r(self.CHOLECALCIFEROL, None, None), ("DDC: not a study drug class", []))

    def test_local_route_code_keeps_the_final_say(self):
        """A study ingredient by a local route (timolol eye drops) is not a clash: the code still decides."""
        self.assertEqual(nabidh._resolve_drug(TIMOLOL_EYE, "TIMOLOL 0.5 MG TABLET", None),
                         ("DDC: non-systemic route", []))


class TestMedicationHandler(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows = [
            ("0000-000000-0000", "VALSARTAN 80 MG TABLET", None),          # placeholder → name
            ("166101", "VALSARTAN 80 MG TABLET", None),                    # stem → code
            ("VMP4763,750 MG,TI", "METFORMIN HCL 750 mg Tablet, Extended Release 24 hr (TI)", None),
            ("VMP182,2 %,OA", "diltiazem HCl 2 % Ointment (gram)", None),   # topical diltiazem: not counted
            (TIMOLOL_EYE, "TIMOLOL 0.5% EYE DROPS", "Ophthalmic"),
            *[(PARACETAMOL, "PANADOL 500 MG", "Oral")] * 12,               # ≥ 10 rows: listed by DDC ingredient
            (PARACETAMOL, "METFORMIN 500 MG TABLET", "Oral"),              # name is about a study drug → name
            (PARACETAMOL, "PANADOL 500 MG, TAKES METFORMIN", "Oral"),      # name only mentions one → code kept
        ]
        cls.out, cls.vc = _meds(rows)

    def test_canonical_rows(self):
        self.assertEqual(sorted(zip(self.out["patient_id"], self.out["atc_code"])),
                         [("P0", "C09CA03"), ("P1", "C09CA03"), ("P17", "A10BA02"), ("P2", "A10BA02")])

    def test_methods(self):
        how = _field(self.vc, "drug → ATC method")
        self.assertEqual(how["name: ingredient"], 1)                                   # placeholder = no code
        self.assertEqual(how["DDC scientific code stem"], 1)
        self.assertEqual(how["code not ATC/DDC → name: trade name + ingredient"], 1)
        self.assertEqual(how["code not ATC/DDC → name: non-systemic"], 1)
        self.assertEqual(how["DDC: non-systemic route"], 1)
        self.assertEqual(how["DDC: not a study drug class"], 13)
        self.assertEqual(how["DDC: not a study drug class → name: trade name + ingredient"], 1)
        self.assertEqual(set(_field(self.vc, "drug code not ATC/DDC")), {"VMP4763,750 MG,TI", "VMP182,2 %,OA"})

    def test_code_format_counts(self):
        self.assertEqual(_field(self.vc, "drug code format"), {
            "DDC product code (9999-999999-9999)": 15, "VMP<id>,<dose>,<form> (no reference)": 2,
            "6 digits (DDC scientific code stem)": 1, "placeholder (all zeros) → no code": 1})

    def test_no_class_lists(self):
        """i22: DDC codes without a study class are listed by the DDC active ingredient (reference data)."""
        self.assertEqual(_field(self.vc, "DDC: not a study drug class (DDC ingredients | route)"),
                         {"PARACETAMOL | ORAL": 13})
        self.assertEqual(_field(self.vc, "DDC: non-systemic route (DDC ingredients | route | row route)"),
                         {"TIMOLOL | OCULAR | row: Ophthalmic": 1})
        used = "DDC code without study class → name used"
        kept = "DDC code without study class, name has one (code kept)"
        self.assertEqual(_field(self.vc, used), {"<n rows>": 1})
        self.assertEqual(_field(self.vc, f"{used}: DDC ≠ name ATC ← name"),
                         {"PARACETAMOL ≠ A10BA02 ← METFORMIN 500 MG TABLET": 1})
        self.assertEqual(_field(self.vc, kept), {"<n rows>": 1})
        self.assertEqual(_field(self.vc, f"{kept}: DDC ≠ name ATC ← name"),
                         {"PARACETAMOL ≠ A10BA02 ← PANADOL 500 MG, TAKES METFORMIN": 1})
        self.assertEqual(_field(self.vc, "rows dropped: no study drug class"), {"<no ATC>": 15})

    def test_no_code_column(self):
        """C3: no DrugProduct_Code → only the name path; no DDC lists."""
        df = pd.DataFrame({"patient_id": ["P1"], "date": [pd.Timestamp("2021-01-01")],
                           "drug_name": ["GLIMEPIRIDE 2 MG TABLET"]})
        vc: list[dict] = []
        out = nabidh._h_medications(df, "medications", vc)["medications"]
        self.assertEqual(list(out["atc_code"]), ["A10BB12"])
        vc = pd.DataFrame(vc)
        self.assertEqual(_field(vc, "drug code format"), {"no code": 1})
        self.assertFalse(vc["field"].str.startswith("DDC").any())


class TestDiagnosisCodes(unittest.TestCase):
    """VM checks (2026-11-20): Diagnosis_Code is ICD-10-CM with dots; C1 has a few trailing dots, C2 a few cells with
    2–3 comma-separated codes."""

    def test_split(self):
        parts, trailing, n = nabidh.split_dx_codes(pd.Series(["E11.9", "E11.9.", "I10, E11.9", "E11.9,I10, Z68.30",
                                                              "R73.03.,", None, " ", "E11.3393"]))
        self.assertEqual(parts.iloc[0], ["E11.9"])
        self.assertEqual(parts.iloc[1], ["E11.9"])
        self.assertEqual(parts.iloc[2], ["I10", "E11.9"])
        self.assertEqual(parts.iloc[3], ["E11.9", "I10", "Z68.30"])
        self.assertEqual(parts.iloc[4], ["R73.03"])
        self.assertTrue(pd.isna(parts.iloc[5]))
        self.assertTrue(pd.isna(parts.iloc[6][0]))
        self.assertEqual(parts.iloc[7], ["E11.3393"])
        self.assertEqual(list(trailing), [False, True, False, False, True, False, False, False])
        self.assertEqual(list(n), [1, 1, 2, 3, 1, 1, 1, 1])

    def test_handler_keeps_the_second_code(self):
        df = pd.DataFrame({"patient_id": ["A", "B", "C"], "code": ["I10, E11.9", "R73.03.", "E66.9"],
                           "date": pd.Timestamp("2021-01-01"), "description": ["x", "y", "z"],
                           "code_system": "ICD-10"})
        vc: list[dict] = []
        out = nabidh._h_conditions(df, "diagnoses", vc)["conditions"]
        self.assertEqual(list(zip(out["patient_id"], out["code"])),
                         [("A", "I10"), ("A", "E11.9"), ("B", "R73.03"), ("C", "E66.9")])
        self.assertEqual(sorted(out.loc[codelists.match_dx(out, "t2d"), "patient_id"]), ["A"])     # lost before
        self.assertEqual(sorted(out.loc[codelists.match_dx(out, "hypertension"), "patient_id"]), ["A"])
        vc = pd.DataFrame(vc)
        self.assertEqual(_field(vc, "code cell with several codes → one row each"), {"2 codes in the cell": 1})
        self.assertEqual(_field(vc, "code: trailing dot removed"), {"<n rows>": 1})
        self.assertEqual(set(out["description"]), {"x", "y", "z"})


def _fh(rows):
    df = pd.DataFrame(rows, columns=["condition", "condition_text", "relation"])
    df.insert(0, "patient_id", [f"P{i}" for i in range(len(df))])
    df["date"] = pd.NaT
    vc: list[dict] = []
    out = nabidh._h_family_history(df, "family_history", vc)["observations"]
    return out, pd.DataFrame(vc)


class TestFamilyHistoryCodes(unittest.TestCase):
    def test_relation_seen_on_vm_all_first_degree(self):
        """FamilyMember_Description values in ≥ 10 patients (C1 / C2, 2026-11-20) are all in the dictionary."""
        for rel in ("Father", "Mother", "Brother", "Sister", "Child", "Parent"):
            self.assertEqual(nabidh.FH_RELATION_DEGREE[rel.lower()], "first", rel)

    def test_relation_by_word(self):
        out, vc = _fh([("73211009", "Diabetes mellitus (disorder)", r) for r in
                       ("Paternal Grandmother", "Maternal aunt", "Grandmother and mother", "Spouse", "Father")])
        self.assertEqual(list(out["value"]), ["positive_non_first_degree", "positive_non_first_degree", "positive",
                                              "positive", "positive"])
        self.assertEqual(_field(vc, "relation → degree"), {
            "paternal grandmother → other (by word)": 1, "maternal aunt → other (by word)": 1,
            "grandmother and mother → first (by word)": 1, "spouse → unmapped (treated as first)": 1,
            "father → first": 1})

    def test_local_codes_recognised_by_text(self):
        """C1 / C2 FamilyHistory.Diagnosis_Code: SNOMED / ICD-10, the word "Diabetes" or local numbers (60376773, 2, 5,
        82680 …); a local code counts only through the description text, and the report lists those codes."""
        rows = [("60376773", "Diabetes mellitus", "Father")] * 11 + [
            ("2", "Type 2 diabetes", "Mother"), ("Diabetes", "Diabetes", "Mother"), ("44054006", None, "Brother"),
            ("Z83.3", None, "Sister"), ("5", "Hypertension", "Father"), ("2", None, "Father")]
        out, vc = _fh(rows)
        self.assertEqual(len(out), 15)                                      # 5 Hypertension and bare "2" dropped
        self.assertEqual(_field(vc, "diabetes recognised by"),
                         {"text only": 13, "SNOMED code": 1, "ICD-10 code": 1})
        self.assertEqual(_field(vc, "text only: Diagnosis_Code"), {"60376773": 11, "2": 1, "Diabetes": 1})


class TestIngestBlock(unittest.TestCase):
    def test_diagnosis_and_family_history_sections(self):
        v = pd.DataFrame({"source": ["diagnoses", "diagnoses", "family_history", "family_history"],
                          "field": ["code cell with several codes → one row each", "code: trailing dot removed",
                                    "text only: Diagnosis_Code", "text only: Diagnosis_Code"],
                          "value": ["2 codes in the cell", "<n rows>", "60376773", "RARE-LOCAL"],
                          "n_rows": ["<10", "12", "384", "<10"]})
        self.assertEqual(enclave.field_summary(v, "diagnoses", enclave.DX_FIELDS)["value"].tolist(),
                         ["2 codes in the cell", "<n rows>"])
        self.assertEqual(enclave.field_summary(v, "family_history", enclave.FH_FIELDS, suffix=True)["value"].tolist(),
                         ["60376773"])                                     # a code with < 10 rows is not printed

    def test_medication_summary_new_lists(self):
        """Block: format counts always; DDC ingredient / disagreement lists only for values with ≥ 10 rows."""
        f_nc = "DDC: not a study drug class (DDC ingredients | route)"
        f_clash = "DDC code without study class → name used: DDC ≠ name ATC ← name"
        v = pd.DataFrame({"source": ["medications"] * 7,
                          "field": ["drug code format", "drug code format", f_nc, f_nc,
                                    "DDC code without study class → name used", f_clash, f_clash],
                          "value": ["DDC product code (9999-999999-9999)", "placeholder (all zeros) → no code",
                                    "PARACETAMOL | ORAL", "RARE INGREDIENT | ORAL", "<n rows>",
                                    "PARACETAMOL ≠ A10BA02 ← METFORMIN 500", "X ≠ C09CA03 ← RARE"],
                          "n_rows": ["19243", "<10", "61", "<10", "12", "11", "<10"]})
        got = enclave.medication_summary(v)["value"].tolist()
        self.assertEqual(got, ["DDC product code (9999-999999-9999)", "placeholder (all zeros) → no code",
                               "PARACETAMOL | ORAL", "<n rows>", "PARACETAMOL ≠ A10BA02 ← METFORMIN 500"])


if __name__ == "__main__":
    unittest.main()
