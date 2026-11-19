"""Dubai Drug Code (DDC) list (DHA, .xlsx) → src/sandbox/reference/ddc.csv.gz.

The DDC list has no ATC code; per product it has active ingredient names, route of administration and dosage
form. The adapter (io/adapters/ddc.py) finds the drug class from this table + codelists.INGREDIENT_ATC. Here the
list is only slimmed down (price, manufacturer, licence holder dropped); the mapping rule stays in code → no need
to rebuild this file when codelists change. When a new DDC list arrives, run again (outside the enclave) and commit.

No dependencies: the .xlsx is read with the standard library (zipfile + xml); no openpyxl needed.

Usage:
  python tools/build_ddc_reference.py ~/Downloads/Dubai_Drug_Code_DDC_List_20261116_193716.xlsx
  python tools/build_ddc_reference.py <xlsx> --out <path>      # default: src/sandbox/reference/ddc.csv.gz
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from sandbox.io.adapters import ddc  # noqa: E402

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REQUIRED = ["DDC_CODE", "SCIENTIFIC_CODE", "TRADE_NAME", "INGREDIENT_STRENGTH", "DOSAGE_FORM_PACKAGE",
            "ROUTE_OF_ADMIN", "STATUS"]


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(path: Path) -> pd.DataFrame:
    """Reads the first sheet; the first row is the header. Cells come back as text."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        sheets = sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        rows = []
        with z.open(sheets[0]) as f:
            for _, el in ET.iterparse(f):
                if el.tag != f"{{{NS['m']}}}row":
                    continue
                cells = {}
                for c in el.findall("m:c", NS):
                    t, v = c.get("t"), c.find("m:v", NS)
                    if t == "s":
                        val = shared[int(v.text)]
                    elif t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
                    else:
                        val = v.text if v is not None else None
                    cells[_col_index(c.get("r"))] = val
                rows.append([cells.get(i) for i in range(max(cells) + 1)] if cells else [])
                el.clear()
    width = len(rows[0])
    return pd.DataFrame([r + [None] * (width - len(r)) for r in rows[1:]], columns=rows[0])


def slim(raw: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED if c not in raw.columns]
    if missing:
        raise SystemExit(f"Expected columns missing from the DDC list: {missing}")
    s = raw[REQUIRED].apply(lambda x: x.astype("string").str.strip())
    return pd.DataFrame({
        "ddc_code": s["DDC_CODE"],
        "scientific_code": s["SCIENTIFIC_CODE"],
        "trade_name": s["TRADE_NAME"].str.replace(r"\s+", " ", regex=True),
        # "METFORMIN HCL/SITAGLIPTIN [500 MG|50 MG]" → active ingredient names (strength in square brackets)
        "ingredients": s["INGREDIENT_STRENGTH"].str.replace(r"\s*\[.*$", "", regex=True).str.strip(),
        # "TABLETS (30'S, BLISTER PACK)" → "TABLETS" (package dropped)
        "dosage_form": s["DOSAGE_FORM_PACKAGE"].str.replace(r"\s*\(.*$", "", regex=True).str.strip(),
        "route": s["ROUTE_OF_ADMIN"],
        "status": s["STATUS"].str.extract(r"^(\w+)", expand=False),       # Active / Grace / Discontinued
    }).dropna(subset=["ddc_code"]).drop_duplicates("ddc_code")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsx", type=Path)
    ap.add_argument("--out", type=Path, default=ddc.REFERENCE_PATH)
    a = ap.parse_args()
    ref = slim(read_xlsx(a.xlsx))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    ref.to_csv(a.out, index=False, compression={"method": "gzip", "mtime": 0})   # same input = same file
    print(f"{len(ref)} products → {a.out}  ({a.out.stat().st_size // 1024} KB)")

    # Summary: which products fell into which ATC group (for review; does not go to the enclave)
    table = ddc.load_reference(a.out)
    hit = table[table["atc_codes"].str.len() > 0]
    print(f"products mapped to study drug classes: {len(hit)}  · not counted because the route is not systemic: "
          f"{int(table['excluded_route'].sum())}")
    by = hit.explode("atc_codes")["atc_codes"].str.slice(0, 3).value_counts().sort_index()
    print("ATC 3 chars → product count:", ", ".join(f"{k} {v}" for k, v in by.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
