"""DDC (Dubai Drug Code) → ATC mapping: active ingredient search, route rule, lookup by code and by name.
Uses the real reference file (src/sandbox/reference/ddc.csv.gz); the codes are products in that list."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sandbox import codelists  # noqa: E402
from sandbox.io.adapters import ddc  # noqa: E402


class TestIngredientTable(unittest.TestCase):
    def test_codes_are_atc_and_in_expected_groups(self):
        atc_like = re.compile(r"^[A-Z]\d{2}([A-Z]{1,2}\d{0,2})?$")
        for ing, atc in codelists.INGREDIENT_ATC.items():
            self.assertRegex(atc, atc_like, ing)
            self.assertTrue(atc.startswith(("A10", "C02", "C03", "C07", "C08", "C09", "C10AA", "H02AB", "N05A")),
                            f"{ing} → {atc}")
        self.assertTrue(all(codelists.INGREDIENT_ATC[k].startswith("A10") for k in codelists.INGREDIENT_ANY_ROUTE))

    def test_word_boundaries_and_combinations(self):
        f = ddc.ingredient_atc
        self.assertEqual(f("AMLODIPINE (AS BESYLATE)/VALSARTAN/HYDROCHLOROTHIAZIDE"), ["C08CA01", "C09CA03", "C03AA03"])
        self.assertEqual(f("LEVAMLODIPINE MALEATE"), ["C08CA"])                 # AMLODIPINE does not match
        self.assertEqual(f("METHYLPREDNISOLONE ACETATE"), ["H02AB04"])          # PREDNISOLONE does not match
        self.assertEqual(f("HYDROCORTISONE"), ["H02AB09"])                      # CORTISONE does not match
        self.assertEqual(f("APRACLONIDINE (AS HCL)"), [])                      # CLONIDINE does not match
        self.assertEqual(f("EZETIMIBE/ROSUVASTATIN (AS CALCIUM)"), ["C10AA07"])
        self.assertEqual(f("NYSTATIN"), [])
        self.assertEqual(f("INSULIN DELIVERY DEVICE"), [])                     # device
        self.assertEqual(f("ISOPHANE INSULIN/RECOMBINANT SOLUBLE HUMAN INSULIN"), ["A10A"])
        self.assertEqual(f(None), [])

    def test_routes(self):
        self.assertTrue(ddc.route_is_systemic("ORAL"))
        self.assertTrue(ddc.route_is_systemic("IM,INTRA-ARTICULAR"))
        self.assertTrue(ddc.route_is_systemic("S.C,IM,IV,EPIDURAL,INFILTRATION"))
        for r in ("TOPICAL", "OCULAR", "OTIC, OCULAR", "NASAL", "ORAL INHALATION", "LOCAL ORAL", "RECTAL",
                  "INTRA-ARTICULAR", "BUCCAL"):
            self.assertFalse(ddc.route_is_systemic(r), r)
        self.assertTrue(ddc.route_is_systemic("N/A", "FILM COATED TABLETS"))   # no route → the form decides
        self.assertFalse(ddc.route_is_systemic(None, "EYE DROPS"))
        self.assertFalse(ddc.route_is_systemic("ORAL", "ORAL PASTE"))           # oromucosal triamcinolone


class TestLookup(unittest.TestCase):
    def test_reference_loads(self):
        ref = ddc.load_reference()
        self.assertGreater(len(ref), 30000)
        self.assertTrue(ref["ddc_code"].is_unique)
        self.assertGreater(int((ref["atc_codes"].str.len() > 0).sum()), 3000)

    def test_code_formats(self):
        for c in ("0321-164101-0391", "03211641010391", " 0321-164101-0391 "):
            self.assertEqual(ddc.lookup_code(c), ("DDC code", ["A10BA02"]), c)
        self.assertEqual(ddc.lookup_code("164101-039"), ("DDC scientific code", ["A10BA02"]))
        self.assertEqual(ddc.lookup_code("0013-627101-0391"), ("DDC code", ["C08CA01", "C09CA03"]))
        self.assertEqual(ddc.lookup_code("12345"), ("not a DDC code", []))
        self.assertEqual(ddc.lookup_code("--"), ("not a DDC code", []))

    def test_code_route_rules(self):
        self.assertEqual(ddc.lookup_code("0169-120501-0371"), ("DDC: non-systemic route", []))   # timolol eye
        self.assertEqual(ddc.lookup_code("0006-106607-1161"), ("DDC: not a study drug class", []))  # paracetamol
        self.assertEqual(ddc.lookup_code("0094-622101-0531"), ("DDC: not a study drug class", []))  # insulin pen
        self.assertEqual(ddc.lookup_code("0235-345201-1021"), ("DDC: not a study drug class", []))  # errata (vaccine)
        # product IM / intra-articular; row route intra-articular → not systemic
        kenacort = ddc.load_reference()
        code = kenacort.loc[kenacort["route"].eq("IM,INTRA-ARTICULAR") & kenacort["ingredients"].str.contains(
            "TRIAMCINOLONE", na=False), "ddc_code"].iloc[0]
        self.assertEqual(ddc.lookup_code(code)[1], ["H02AB08"])
        self.assertEqual(ddc.lookup_code(code, "Intra-articular"), ("DDC: non-systemic route", []))

    def test_names(self):
        f = lambda n, r=None: ddc.lookup_name(n, r)[1]  # noqa: E731
        self.assertEqual(f("CRESTOR 10 MG"), ["C10AA07"])                      # "CRESTOR 10MG" in DDC
        self.assertEqual(f("Tab. Lipitor 20mg"), ["C10AA05"])
        self.assertEqual(f("CONCOR PLUS 5/12.5"), ["C03AA03", "C07AB07"])      # longest brand stem
        self.assertEqual(f("JANUMET 50/1000"), ["A10BH01", "A10BA02"])
        self.assertEqual(f("metformin 500 mg"), ["A10BA02"])
        self.assertEqual(f("Dexamethasone 0.1% eye drops"), [])
        self.assertEqual(f("DEXAMETHASONE 4MG TABLETS"), ["H02AB02"])
        self.assertEqual(f("Prednisolone", "Ophthalmic"), [])                  # row route is local
        self.assertEqual(f("BETNOVATE CREAM"), [])
        self.assertEqual(f("Insulin pen needles"), [])
        self.assertEqual(f("Paracetamol 500mg"), [])
        self.assertEqual(ddc.lookup_name(None), ("no name", []))

    def test_brand_first_word(self):
        # The DDC name has a suffix ("XIGDUO XR 5MG/1000MG", "TOUJEO SOLOSTAR"); the row does not → brand first word
        self.assertEqual(ddc.lookup_name("XIGDUO 5/1000 EXTENDED RELEASE TABLETS"),
                         ("name: brand first word", ["A10BK01", "A10BA02"]))
        self.assertEqual(ddc.lookup_name("xigduo"), ("name: brand first word", ["A10BK01", "A10BA02"]))
        self.assertEqual(ddc.lookup_name("XIGDUO XR 10MG/1000MG")[0], "name: trade name")   # full name first
        self.assertEqual(ddc.lookup_name("TOUJEO"), ("name: brand first word", ["A10A"]))
        self.assertEqual(ddc.lookup_name("DIAMICRON 60"), ("name: brand first word", ["A10BB09"]))
        # codes common to the brand, not the union: CONCOR PLUS's thiazide does not reach CONCOR
        self.assertEqual(ddc.lookup_name("CONCOR 5")[1], ["C07AB07"])
        self.assertEqual(ddc.lookup_name("XIGDUO eye drops"), ("name: non-systemic", []))
        self.assertEqual(ddc.lookup_name("Insulin pen needles"), ("name: no study drug class", []))   # device


if __name__ == "__main__":
    unittest.main()
