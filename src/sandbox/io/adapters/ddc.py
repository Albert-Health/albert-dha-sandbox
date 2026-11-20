"""Dubai Drug Code (DDC) → ATC: drug code or drug name in the Medication view → study drug classes.

The NABIDH Medication view has no ATC. C1 and C2 have DrugProduct_Code (mostly the DDC product code, e.g.
"0005-379302-1171", or the DDC scientific code; VM ingest 2026-11-19) and DrugProduct_Description (drug name); C3
has only the name (the earlier "C2 has no drug code" was C3, read as C2 before ingest 1.1.0). Other code shapes seen
(C1 / C2, 2026-11-19): 6 digits = the DDC scientific code stem without its dosage-form suffix ("166101" → valsartan;
the middle part of the product code) → looked up as a stem; "VMP<id>,<dose>,<form>" (another formulary, no reference
here) and the all-zero placeholder "0000-000000-0000" (= no code) → the name decides (code_format). The DDC list has
no ATC either; per product it has active ingredient names ("METFORMIN HCL/SITAGLIPTIN"), route of administration
and dosage form. Mapping:

  product → active ingredients → codelists.INGREDIENT_ATC (whole-word search) → ATC codes
  combination product → one ATC per active ingredient (one Medication row → several canonical rows)
  non-systemic route (eye drops, cream, nasal spray, inhaler, rectal, intra-articular) → no class
  (except insulin: codelists.INGREDIENT_ANY_ROUTE); the row's own route (Route_Description) is checked too

Without a code, the name: (1) if the start of the name matches a DDC trade name, those products' ATCs; failing
that, the brand's first word ("XIGDUO 5/1000" → DDC "XIGDUO XR 5MG/1000MG"), (2) the active ingredient names found
in the name. The union of both is taken. Reference: src/sandbox/reference/ddc.csv.gz
(tools/build_ddc_reference.py).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

from ... import codelists

REFERENCE_PATH = Path(__file__).resolve().parents[2] / "reference" / "ddc.csv.gz"

# Systemic routes in DDC ROUTE_OF_ADMIN (one is enough in a comma-separated list: "IM,INTRA-ARTICULAR" → IM)
SYSTEMIC_ROUTES = {
    "ORAL", "IV", "IV INFUSION", "IV BOLUS", "IM", "SC", "SC INFUSION", "SUBLINGUAL", "TRANSDERMAL",
    "PARENTERAL", "ENTERAL", "INTRAVENOUS", "INTRAMUSCULAR", "SUBCUTANEOUS",
}   # no BUCCAL: the list only has oromucosal hydrocortisone (local)
# Known errors in the DDC list: product code → why it is treated as having no class
REFERENCE_ERRATA = {
    "0235-345201-1021": "MMR vaccine; DDC lists SAXAGLIPTIN among its active ingredients",
}
# Words in free text (the row's route, drug name) that indicate non-systemic use
_LOCAL_WORDS = (r"TOPICAL|CUTANEOUS|DERMAL|EXTERNAL|CREAM|OINTMENT|GEL|LOTION|SHAMPOO|FOAM|OCULAR|OPHTHALMIC|"
                r"EYE|EAR|OTIC|DROPS|NASAL|INHALATION|INHALER|INHALED|NEBULI[SZ]ER|RECTAL|ENEMA|SUPPOSITOR(Y|IES)|"
                r"VAGINAL|INTRA-?ARTICULAR|INTRAVITREAL|INTRALESIONAL|MOUTHWASH|LOCAL")
LOCAL_TEXT = re.compile(rf"(?<![A-Z])({_LOCAL_WORDS})(?![A-Z])")
SYSTEMIC_TEXT = re.compile(r"(?<![A-Z])(ORAL|IV|IM|SC|INTRAVENOUS|INTRAMUSCULAR|SUBCUTANEOUS|TABLETS?|CAPSULES?|"
                           r"INJECTION|INFUSION|SUBLINGUAL|TRANSDERMAL|PO)(?![A-Z])")
LOCAL_FORM = re.compile(r"(?<![A-Z])(PASTE|MOUTHWASH|GARGLE|LOZENGES?|PELLETS?|OROMUCOSAL)(?![A-Z])")
_NOT_A_DRUG = re.compile(rf"(?<![A-Z])({codelists.INGREDIENT_NOT_A_DRUG})(?![A-Z])")
_INGREDIENT = re.compile(
    r"(?<![A-Z])(" + "|".join(re.escape(k) for k in sorted(codelists.INGREDIENT_ATC, key=len, reverse=True))
    + r")(?![A-Z])")
_ANY_ROUTE_ATC = {codelists.INGREDIENT_ATC[k] for k in codelists.INGREDIENT_ANY_ROUTE}


def norm_code(s: pd.Series) -> pd.Series:
    """Code comparison: upper case, letters + digits only ("0005-379302-1171" = "00053793021171")."""
    return s.astype("string").str.upper().str.replace(r"[^0-9A-Z]", "", regex=True).replace("", pd.NA)


def _norm_one(code) -> str:
    return "" if code is None or pd.isna(code) else re.sub(r"[^0-9A-Z]", "", str(code).upper())


# Drug code shapes in Medication.DrugProduct_Code (C1 / C2 ingest, 2026-11-19), checked in this order on the code
# (upper case, stripped). Report only (ingest block "drug code format"), except: a placeholder counts as no code, a
# stem is looked up in the DDC list (lookup_code).
STEM_SHAPE = re.compile(r"^(?:\d{6}|[A-Z]\d{5})$")      # DDC scientific code without the "-999" form suffix
CODE_FORMATS = [
    ("DDC product code (9999-999999-9999)", re.compile(r"^\d{4}-?\d{6}-?\d{4}$")),
    ("DDC scientific code (999999-999)", re.compile(r"^(?:\d{6}|[A-Z]\d{5})-?\d{3}$")),
    ("6 digits (DDC scientific code stem)", STEM_SHAPE),
    ("VMP<id>,<dose>,<form> (no reference)", re.compile(r"^VMP\d+(?:,|$)")),
    ("ATC", re.compile(r"^[A-Z]\d{2}(?:[A-Z]{1,2}\d{0,2})?$")),
]


def is_placeholder(code) -> bool:
    """All-zero code ("0000-000000-0000", 0000…): a filler, not a product → treated as no code."""
    k = _norm_one(code)
    return bool(k) and set(k) == {"0"}


def code_format(code) -> str:
    """Drug code → shape label (CODE_FORMATS; "no code", "placeholder (all zeros) → no code", "other")."""
    c = "" if code is None or pd.isna(code) else str(code).strip().upper()
    if not c:
        return "no code"
    if is_placeholder(c):
        return "placeholder (all zeros) → no code"
    return next((lab for lab, rx in CODE_FORMATS if rx.match(c)), "other")


def _norm_text(s) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^0-9A-Z]+", " ", str(s).upper())).strip()


_LEADING_FORM_WORDS = {"TAB", "TABS", "TABLET", "TABLETS", "CAP", "CAPS", "CAPSULE", "CAPSULES", "INJ", "INJECTION",
                       "SYR", "SYRUP", "SUSP", "AMP", "VIAL"}


def _brand_stem(norm: str) -> str:
    """Normalised name → brand stem: leading form words are dropped, everything from the first word with a digit on
    is dropped ("TAB CRESTOR 10 MG" → "CRESTOR", "CONCOR AM 5MG 5MG" → "CONCOR AM")."""
    words = norm.split()
    while words and words[0] in _LEADING_FORM_WORDS:
        words = words[1:]
    stem = []
    for w in words:
        if any(ch.isdigit() for ch in w):
            break
        stem.append(w)
    return " ".join(stem)


def ingredient_atc(text) -> list[str]:
    """Active ingredient text ("AMLODIPINE (AS BESYLATE)/VALSARTAN") → ATC codes (order kept, no duplicates).
    "/"-separated parts that are devices (insulin pump etc.) are skipped."""
    if text is None or pd.isna(text):
        return []
    out: list[str] = []
    for part in str(text).upper().split("/"):
        if _NOT_A_DRUG.search(part):
            continue
        for m in _INGREDIENT.finditer(part):
            atc = codelists.INGREDIENT_ATC[m.group(1)]
            if atc not in out:
                out.append(atc)
    return out


def route_is_systemic(route, dosage_form=None) -> bool:
    """DDC product route → is it systemic. Without a route / with "N/A" the dosage form decides."""
    r = "" if route is None or pd.isna(route) else str(route).upper()
    tokens = {re.sub(r"\s+", " ", t.replace(".", "")).strip() for t in re.split(r"[,&]| - ", r)}
    form = "" if dosage_form is None or pd.isna(dosage_form) else str(dosage_form).upper()
    if tokens & SYSTEMIC_ROUTES:
        return not LOCAL_FORM.search(form)          # "ORAL" + oromucosal paste (ADCORTYL IN ORABASE) → local
    if tokens - {"", "N/A", "MISCELLANEOUS"}:
        return False
    return bool(SYSTEMIC_TEXT.search(form)) and not LOCAL_TEXT.search(form)


def text_is_local(text) -> bool:
    """Does free text (row route or drug name) clearly say local use (with no systemic word)."""
    if text is None or pd.isna(text):
        return False
    t = str(text).upper()
    return bool(LOCAL_TEXT.search(t)) and not SYSTEMIC_TEXT.search(t)


def _systemic_filter(atcs: list[str], systemic: bool) -> list[str]:
    return atcs if systemic else [a for a in atcs if a in _ANY_ROUTE_ATC]


@lru_cache(maxsize=4)
def load_reference(path: Path | None = None) -> pd.DataFrame:
    """DDC reference + per product `atc_codes` (by the systemic rule) and `excluded_route` (active ingredient
    in a study class but the route is not systemic)."""
    ref = pd.read_csv(path or REFERENCE_PATH, dtype="string", keep_default_na=False, na_values=[""])
    raw_atc = [[] if c in REFERENCE_ERRATA else ingredient_atc(i) for c, i in zip(ref["ddc_code"], ref["ingredients"])]
    systemic = [route_is_systemic(r, f) for r, f in zip(ref["route"], ref["dosage_form"])]
    ref["atc_codes"] = [_systemic_filter(a, s) for a, s in zip(raw_atc, systemic)]
    ref["excluded_route"] = [bool(a) and not b for a, b in zip(raw_atc, ref["atc_codes"])]
    ref["key"] = norm_code(ref["ddc_code"])
    ref["sci_key"] = norm_code(ref["scientific_code"])
    ref["trade_key"] = ref["trade_name"].map(_norm_text)
    return ref


@lru_cache(maxsize=4)
def _indexes(path: Path | None = None):
    ref = load_reference(path)
    by_code = dict(zip(ref["key"], zip(ref["atc_codes"], ref["excluded_route"])))
    by_sci = {}
    for k, a, e in zip(ref["sci_key"], ref["atc_codes"], ref["excluded_route"]):
        by_sci.setdefault(k, (a, e))
    # Trade name keys: full name ("CRESTOR 10MG") + brand stem ("CRESTOR"). A key that also belongs to a non-study
    # product (same name, another drug) is ambiguous → not used. The same brand with only a local route (eye
    # drops etc.) is not ambiguity; the row's own text (text_is_local) makes that distinction.
    kinds: dict[str, set[str]] = {}
    atc_by: dict[str, list[str]] = {}
    # Brand first word: rows often drop the suffix of the DDC name ("XIGDUO" for "XIGDUO XR 5MG/1000MG", "TOUJEO"
    # for "TOUJEO SOLOSTAR"). Same ambiguity rule over every product whose brand stem starts with that word; ATC =
    # the codes common to all its study products (not the union: "CONCOR" must not take CONCOR PLUS's thiazide).
    head_kinds: dict[str, set[str]] = {}
    head_atc: dict[str, list[str]] = {}
    for full, a, e in zip(ref["trade_key"], ref["atc_codes"], ref["excluded_route"]):
        kind = "study" if a else ("local" if e else "other")
        stem = _brand_stem(full)
        for k in {full, stem}:
            if len(k) < 4:
                continue
            kinds.setdefault(k, set()).add(kind)
            cur = atc_by.setdefault(k, [])
            cur.extend(x for x in a if x not in cur)
        head = stem.split()[0] if stem else ""
        if len(head) < 4:
            continue
        head_kinds.setdefault(head, set()).add(kind)
        if a:
            head_atc[head] = list(a) if head not in head_atc else [x for x in head_atc[head] if x in a]
    by_trade = {k: atc_by[k] for k, kd in kinds.items() if "study" in kd and "other" not in kd}
    by_head = {h: head_atc[h] for h, kd in head_kinds.items()
               if "study" in kd and "other" not in kd and head_atc.get(h)}
    return by_code, by_sci, by_trade, by_head


@lru_cache(maxsize=4)
def _stem_index(path: Path | None = None) -> dict[str, tuple[list[str], bool]]:
    """Scientific code stem (first 6 characters, = the middle part of the product code: ingredient + strength without
    the dosage form) → (ATC list, excluded_route). Every product of the stem must agree: all study products → the
    ATC codes common to all of them; all without a class → ([], False) or all local route → ([], True). A stem that
    mixes systemic and local forms (prednisolone tablets + enema) is left out → the drug name decides."""
    ref = load_reference(path)
    kinds: dict[str, set[str]] = {}
    atc: dict[str, list[str]] = {}
    for k, a, e in zip(ref["sci_key"].str.slice(0, 6), ref["atc_codes"], ref["excluded_route"]):
        if pd.isna(k):
            continue
        kinds.setdefault(k, set()).add("study" if a else ("local" if e else "other"))
        if a:
            atc[k] = list(a) if k not in atc else [x for x in atc[k] if x in a]
    out = {}
    for k, kd in kinds.items():
        if kd == {"study"} and atc.get(k):
            out[k] = (atc[k], False)
        elif kd in ({"other"}, {"local"}):
            out[k] = ([], kd == {"local"})
    return out


@lru_cache(maxsize=4)
def _info_index(path: Path | None = None) -> dict[str, str]:
    """Product / scientific code / stem key → "ACTIVE INGREDIENTS | route" from the DDC list (first product) — for the
    ingest report (which ingredient a code without a study class carries; reference data, not patient data)."""
    ref = load_reference(path)
    text = (ref["ingredients"].fillna("?").str.upper() + " | " + ref["route"].fillna(ref["dosage_form"]).fillna("?"))
    out: dict[str, str] = {}
    for keys in (ref["key"], ref["sci_key"], ref["sci_key"].str.slice(0, 6)):
        for k, t in zip(keys, text):
            if not pd.isna(k):
                out.setdefault(k, t)
    return out


def code_info(code, path: Path | None = None) -> str | None:
    """DDC code (product, scientific or stem) → "ACTIVE INGREDIENTS | route" from the DDC list; None if not in it."""
    k = _norm_one(code)
    return _info_index(path).get(k) if k else None


def lookup_code(code, row_route=None, path: Path | None = None) -> tuple[str, list[str]]:
    """DDC product code (or DDC scientific code, or its 6-character stem) → (status, ATC list).
    status: "DDC code" · "DDC scientific code" · "DDC scientific code stem" · "DDC: not a study drug class" ·
    "DDC: non-systemic route" · "not a DDC code". A placeholder (all zeros) is "not a DDC code"."""
    by_code, by_sci, _, _ = _indexes(path)
    key = norm_code(pd.Series([code])).iloc[0]
    if pd.isna(key) or is_placeholder(key):
        return "not a DDC code", []
    hit, how = by_code.get(key), "DDC code"
    if hit is None:
        hit, how = by_sci.get(key), "DDC scientific code"
    if hit is None and STEM_SHAPE.match(key):
        hit, how = _stem_index(path).get(key), "DDC scientific code stem"
    if hit is None:
        return "not a DDC code", []
    atcs, excluded = hit
    if atcs and text_is_local(row_route):
        atcs, excluded = _systemic_filter(atcs, False), True
    if not atcs:
        return ("DDC: non-systemic route" if excluded else "DDC: not a study drug class"), []
    return how, list(atcs)


def name_leads_with_study_drug(name, path: Path | None = None) -> bool:
    """Is the drug name about a study drug: its brand stem (the words before the first number, leading form words
    dropped) is a study trade name / brand, or names a study active ingredient ("DAPAGLIFLOZIN 5 MG-METFORMIN ER …",
    "DAPAGLIFLOZIN/METFORMIN 5 MG/1000 MG", "XIGDUO XR 5/1000"). Free text that only mentions one later on
    ("VITAMIN D3 1000 IU (ON METFORMIN)", "PANADOL 500 MG, TAKES METFORMIN") is not. Devices never are."""
    if name is None or pd.isna(name) or _NOT_A_DRUG.search(str(name).upper()):
        return False
    _, _, by_trade, by_head = _indexes(path)
    words = _brand_stem(_norm_text(name)).split()
    if not words:
        return False
    if any(by_trade.get(" ".join(words[:k])) for k in range(min(len(words), 6), 0, -1)) or by_head.get(words[0]):
        return True
    return bool(ingredient_atc(" ".join(words)))


def lookup_name(name, row_route=None, path: Path | None = None) -> tuple[str, list[str]]:
    """Drug name (free text) → (status, ATC list). Trade name (DDC, start of the name) + active ingredients named.
    status: "name: trade name" · "name: brand first word" · "name: ingredient" · "name: trade name + ingredient" ·
    "name: brand first word + ingredient" · "name: non-systemic" · "name: no study drug class"."""
    if name is None or pd.isna(name) or not str(name).strip():
        return "no name", []
    _, _, by_trade, by_head = _indexes(path)
    norm = _norm_text(name)
    device = bool(_NOT_A_DRUG.search(str(name).upper()))
    trade: list[str] = by_trade.get(norm, [])
    trade_how = "trade name"
    words = _brand_stem(norm).split()
    for k in range(min(len(words), 6), 0, -1):          # longest brand stem first ("CONCOR PLUS" > "CONCOR")
        if trade:
            break
        trade = by_trade.get(" ".join(words[:k]), [])
    if not trade and words and not device:              # looser key: never for a device ("INSULIN PEN NEEDLES")
        trade, trade_how = list(by_head.get(words[0], [])), "brand first word"
    ingr = [] if device else ingredient_atc(str(name).replace("/", " "))
    atcs = trade + [a for a in ingr if a not in trade]
    if not atcs:
        return "name: no study drug class", []
    if text_is_local(name) or text_is_local(row_route):
        atcs = _systemic_filter(atcs, False)
        if not atcs:
            return "name: non-systemic", []
    how = "name: " + " + ".join(w for w, x in ((trade_how, trade), ("ingredient", ingr)) if x)
    return how, atcs
