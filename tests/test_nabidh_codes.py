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
            (PARACETAMOL, "METFORMIN 500 MG TABLET", "Oral"),              # code and name disagree
        ]
        cls.out, cls.vc = _meds(rows)

    def test_canonical_rows(self):
        self.assertEqual(sorted(zip(self.out["patient_id"], self.out["atc_code"])),
                         [("P0", "C09CA03"), ("P1", "C09CA03"), ("P2", "A10BA02")])   # the code keeps the final say

    def test_methods(self):
        how = _field(self.vc, "drug → ATC method")
        self.assertEqual(how["name: ingredient"], 1)                                   # placeholder = no code
        self.assertEqual(how["DDC scientific code stem"], 1)
        self.assertEqual(how["code not ATC/DDC → name: trade name + ingredient"], 1)
        self.assertEqual(how["code not ATC/DDC → name: non-systemic"], 1)
        self.assertEqual(how["DDC: non-systemic route"], 1)
        self.assertEqual(how["DDC: not a study drug class"], 13)
        self.assertEqual(set(_field(self.vc, "drug code not ATC/DDC")), {"VMP4763,750 MG,TI", "VMP182,2 %,OA"})

    def test_code_format_counts(self):
        self.assertEqual(_field(self.vc, "drug code format"), {
            "DDC product code (9999-999999-9999)": 14, "VMP<id>,<dose>,<form> (no reference)": 2,
            "6 digits (DDC scientific code stem)": 1, "placeholder (all zeros) → no code": 1})

    def test_no_class_lists(self):
        """i22: DDC codes without a study class are listed by the DDC active ingredient (reference data)."""
        self.assertEqual(_field(self.vc, "DDC: not a study drug class (DDC ingredients | route)"),
                         {"PARACETAMOL | ORAL": 13})
        self.assertEqual(_field(self.vc, "DDC: non-systemic route (DDC ingredients | route | row route)"),
                         {"TIMOLOL | OCULAR | row: Ophthalmic": 1})
        self.assertEqual(_field(self.vc, "DDC code without study class, drug name has one"), {"<n rows>": 1})
        self.assertEqual(
            _field(self.vc, "DDC code without study class, drug name has one: DDC ≠ name ATC ← name"),
            {"PARACETAMOL ≠ A10BA02 ← METFORMIN 500 MG TABLET": 1})
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


class TestIngestBlock(unittest.TestCase):
    def test_medication_summary_new_lists(self):
        """Block: format counts always; DDC ingredient / disagreement lists only for values with ≥ 10 rows."""
        f_nc = "DDC: not a study drug class (DDC ingredients | route)"
        f_clash = "DDC code without study class, drug name has one: DDC ≠ name ATC ← name"
        v = pd.DataFrame({"source": ["medications"] * 7,
                          "field": ["drug code format", "drug code format", f_nc, f_nc,
                                    "DDC code without study class, drug name has one", f_clash, f_clash],
                          "value": ["DDC product code (9999-999999-9999)", "placeholder (all zeros) → no code",
                                    "PARACETAMOL | ORAL", "RARE INGREDIENT | ORAL", "<n rows>",
                                    "PARACETAMOL ≠ A10BA02 ← METFORMIN 500", "X ≠ C09CA03 ← RARE"],
                          "n_rows": ["19243", "<10", "61", "<10", "12", "11", "<10"]})
        got = enclave.medication_summary(v)["value"].tolist()
        self.assertEqual(got, ["DDC product code (9999-999999-9999)", "placeholder (all zeros) → no code",
                               "PARACETAMOL | ORAL", "<n rows>", "PARACETAMOL ≠ A10BA02 ← METFORMIN 500"])


if __name__ == "__main__":
    unittest.main()
