"""NABIDH (enclave) raw data → canonical schema.

Delivery layout (NABIDH "Data availability", 2026-11-13; as seen in the enclave 2026-11-18; C1 DDL
2026-11-19): one IRIS schema per cohort (HSSBX namespace, *_HSAA) holding HSAA views — Patient (ID,
Age, Gender_Code, EthnicGroup_Description; no date of birth or nationality) · Diagnosis · Observation (vitals;
no unit) · LabResultItem (labs; with unit) · SocialHistory · FamilyHistory · Medication · Encounter (not in the
C1 DDL). Patient key: Patient.ID = Patient in the other views.
Raw files: data/nabidh/raw/<c1|c2|c3>/ (as delivered by DHA; never modified).

Two input paths, one mapping:
- raw file   `load(raw_dir, cohort)`            reads each source's `file` (data/nabidh/raw/<cohort>/)
- IRIS       `load_iris(conn, cohort)`          reads each source's `table` (or `query`) from InterSystems
             IRIS at DHA (io/iris.py); the result is turned into text as in the raw file and, if
             `snapshot_dir` is given, written as CSV under the same `file` names → that folder can then
             be read again, identically, through the raw-file path (reproducibility, audit hash).
Column mapping, filters, dates, value dictionaries and handlers are shared by both paths.

Work to do in the enclave (should need no code change):
1. Replace the file / table and column names in SOURCES with the real ones. The ones below are examples;
   tools/make_nabidh_dryrun.py builds the dry-run data (CSV + SQLite in place of IRIS) with these names.
   IRIS: look at the schema in the IntelliJ Database tool; `table` = "<SCHEMA>.<Table>" (the {schema} and
   {cohort} placeholders are filled from IRIS_COHORTS). Column names are matched case-insensitively and
   only the columns named in the mapping are fetched (nothing extra such as identifying data). If a join /
   filter is needed, give the source a full `query` (SELECT only; rename columns with AS to the `columns` names).
2. If the date format is not ISO, set DATE_FORMAT (e.g. "%d/%m/%Y"; for the IRIS internal date number
   "horolog" = days since 1840-12-31, "day,seconds" also works); separator / encoding in CSV_OPTIONS.
3. Run tools/ingest_nabidh.py (--input iris for IRIS). For values shown as "unmapped" in
   outputs/<run_id>/ingest/<cohort>_value_counts.csv, extend SMOKING_VALUES, FH_STATUS_VALUES,
   FH_RELATION_DEGREE and codelists.NATIONALITY_COUNTRIES; run again.

Source kinds (kind) → canonical table:
  patients        → patients (sex → Male / Female via SEX_MAP)
  conditions      → conditions (code system normalised to ICD-10 / SNOMED)
  measurements    → labs + observations (codes in codelists.LOINC_LAB are labs, the rest observations)
  lab_results     → labs (codelists.LOINC_LAB codes only; other tests are dropped, they are not observations —
                    a code | unit | name list and the value distribution per kind | unit are reported)
  medications     → medications; without ATC, DDC product code / drug name → ATC (io/adapters/ddc.py,
                    src/sandbox/reference/ddc.csv.gz); combination → one row per active ingredient
  labs, observations, encounters → as is
  smoking         → observations, concept = smoking_status; value via SMOKING_VALUES
                    never / ex / current / light / moderate / heavy / unknown
  family_history  → observations, concept = family_history_dm; value positive / negative /
                    positive_non_first_degree / unknown (diabetes records only)
Several sources can feed one canonical table (e.g. Observation + SocialHistory → observations).
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import pandas as pd

from ... import codelists
from .. import explore, iris
from . import ddc
from ..schema import SCHEMA, TABLES, Dataset, coerce
from .synthetic import read_raw_csv

# Ingest version: shown in every COPY block header, the ingest output, the ingest summary, the audit and next to
# the canonical data (<cohort>/ingest.json → NB0 / NB1 blocks). Bump it when adapter or ingest behaviour changes:
#   MAJOR canonical schema · MINOR mapping / dictionary / handler (canonical data may change) · PATCH report / output.
# Log (newest first):
#   unreleased (1c)  2026-11-20  LabResultItem: a decimal comma ("6,2") is read as a point; a result that is not a
#                      finite number ("<5.0", text) is dropped and counted by kind | shape (labs "missing required
#                      value" ERROR); comparators are not read as their bound
#   1.3.0  2026-11-20  1c · LabResultItem: one spelling per unit (LAB_UNITS; "0" / "NULL" unit = no unit),
#                      rows with an empty value dropped and counted per code (drop_empty; the text "NULL" = empty).
#                      Observation (vitals): "0" / "-" = empty (empty_values, counted), height 1.2–2.3 m → cm,
#                      value distribution per vital in the report
#                      1d · Medication: a 6-digit code = DDC scientific code stem, looked up when every product
#                      of the stem agrees; the all-zero placeholder "0000-000000-0000" = no code (→ name). Report:
#                      "drug code format" counts; DDC codes without a study class listed by DDC ingredient | route
#                      (i22) and code / name disagreement counted (code keeps the final say). Diagnosis: a cell with
#                      several comma-separated codes → one row per code, trailing dot removed (counted). Family
#                      history: a relationship not in FH_RELATION_DEGREE is decided by its words ("maternal aunt" →
#                      other); report lists the codes recognised by text only
#   1.2.1  2026-11-19  Progress lines on screen: IRIS connection, each view's query, rows so far, mapping time
#                      (output only; canonical data unchanged)
#   1.2.0  2026-11-19  Observation: rows with an empty value are dropped and counted per code (SOURCES drop_empty;
#                      the C1 "missing required value" ERRORs were empty vital rows)
#   1.1.1  2026-11-19  English comments, messages and report text (output wording only; mapping unchanged)
#   1.1.0  2026-11-19  IRIS_COHORTS: C2 and C3 schemas swapped (the earlier "C2" data was really C3)
#   1.0.0  2026-11-19  HSAA views; LabResultItem labs with units (eAG / RBS dropped by name, plausibility
#                      report); SocialHistory tobacco item filter + intensity dictionary; family history: ICD-10 /
#                      SNOMED code first then text, negation, relative degree, prediabetes dropped; DDC → ATC
INGEST_VERSION = "1.3.0"

CSV_OPTIONS = {"sep": ",", "encoding": "utf-8-sig"}
DATE_FORMAT: str | None = None          # None = ISO-8601 / pandas inference; e.g. "%d/%m/%Y"; "horolog" (IRIS)
HOROLOG_EPOCH = pd.Timestamp("1840-12-31")   # IRIS $HOROLOG: day 0

# The patient view has no date of birth, only age (Age, whole years). Date of birth is derived from age:
# AGE_REFERENCE_DATE − (Age + 0.5) years (assumes mid-year on the day age was given; error ≤ ±6 months).
# [DECISION PENDING] D24 — Age as of which date (data extract / view creation / query day)? To ask DHA;
# if birth year or date can be provided, the BirthDate column is preferred (optional_columns).
# Interim value: the day the views were first queried (2026-11-18).
AGE_REFERENCE_DATE = "2026-11-18"

# Per-cohort placeholders in IRIS: {schema} etc. in `table` / `query` come from here, {cohort} from the cohort name.
# DHA enclave (namespace HSSBX, 2026-11-18): one HSAA schema per cohort, holding views.
# C2 and C3 were swapped until 2026-11-19 (ingest < 1.1.0): what was read as "C2" was the C3 schema.
IRIS_COHORTS: dict[str, dict[str, str]] = {
    "c1": {"schema": "SBXV_ENCL447CCD80_HSAA"},
    "c2": {"schema": "SBXV_ENCL94F43B4B_HSAA"},
    "c3": {"schema": "SBXV_ENCL6F10EFBD_HSAA"},
}

# Source definition:
#   file              file name in the cohort folder (for IRIS: the snapshot file name)
#   table             IRIS table, e.g. "{schema}.Patient" (IRIS_COHORTS placeholders)
#   query             (optional) a full SELECT instead of table; must return columns under the `columns` names
#   kind              one of the source kinds above
#   columns           {canonical_name: source_column} — required; KeyError if absent. The source column can
#                     also be a list: if the name differs between cohorts, the first one present is taken
#   optional_columns  {canonical_name: source_column (or list)} — taken if present
#   constants         {canonical_name: value} — this value if the column is absent or empty
#   filter            {source_column or canonical_name: [allowed values]} — case-insensitive selection
#   drop_empty        [canonical_name, ...] — rows whose value there is empty (NULL / blank / the text "NULL") are
#                     dropped and counted (report: dropped_empty_<name>, with a per-code breakdown when the source
#                     has `code`)
#   empty_values      {canonical_name: [text, ...]} — with drop_empty: these values count as empty too (case-insensitive;
#                     a number equal to one of them as well, "0.0" = "0"); of which: dropped_empty_<name>_placeholder
#   optional          True → skipped if the file / table is absent (e.g. encounter only in C3)
#   date_format       overrides DATE_FORMAT for this source
#
# HSAA views (2026-11-18, check_environment [mapping] output): the patient key is the numeric `ID` in the
# Patient view and the `Patient` column carrying the same value in the other views. Cohort differences: C3 (read as
# "C2" before ingest 1.1.0) has SocialHabitCategory_Description instead of _Code and no DrugProduct_Code in
# Medication — the real C2 has drug codes (VM ingest 2026-11-19: DDC code 21,099 rows, scientific code 3,127); C1
# has no SELECT permission on Encounter (optional, skipped). Code systems (VM checks 2026-11-20, C1 / C2):
# Diagnosis_Code is ICD-10-CM with dots (split_dx_codes), ObservationCode_Code LOINC (only 3141-9, 8302-2, 39156-5).
# In the C1 DDL (2026-11-19) but not mapped: Diagnosis.DiagnosisGroup (values unknown), Medication
# ToTime / DoseQuantity / DoseUoM_Description, Observation.Encounter, LabResultItem ID / Encounter.
SOURCES: dict[str, dict] = {
    "patient_profile": {
        "file": "patients.csv", "table": "{schema}.Patient", "kind": "patients",
        "columns": {"patient_id": "ID", "sex": "Gender_Code", "age": "Age"},
        "optional_columns": {"ethnicity_raw": "EthnicGroup_Description", "nationality": "Nationality",
                             "date_of_birth": "BirthDate"},
    },
    "diagnoses": {
        "file": "diagnoses.csv", "table": "{schema}.Diagnosis", "kind": "conditions",
        "columns": {"patient_id": "Patient", "code": "Diagnosis_Code", "date": "DiagnosisDate"},
        "optional_columns": {"description": "Diagnosis_Description"},
        "constants": {"code_system": "ICD-10"},
    },
    "observations": {
        "file": "observations.csv", "table": "{schema}.Observation", "kind": "measurements",
        "columns": {"patient_id": "Patient", "code": "ObservationCode_Code", "value": "ObservationValue",
                    "date": "ObservationDate"},
        "optional_columns": {"test_name": "ObservationCode_Description"},     # no unit column
        "constants": {"code_system": "LOINC"},
        # C1 (2026-11-19): Observation holds only vitals (3141-9 weight, 8302-2 height, 39156-5 BMI); rows with an
        # empty ObservationValue carry nothing and were the "missing required value" schema ERRORs → dropped.
        "drop_empty": ["value"],
        # VM checks (2026-11-20; C1 and C2 hold only these three vitals): "0" is a placeholder (BMI p25 = 0; one-digit
        # values 38% of C1 / 27% of C2 BMI rows, ~1–2% of height and weight), "-" too → dropped as empty and counted.
        "empty_values": {"value": ["0", "-"]},
    },
    # LabResultItem (C1 DDL, 2026-11-19): ID, Encounter, Patient, ResultDate, ResultValue, ResultValueUnits,
    # TestItemCode_Code, TestItemCode_Description. The first ingest had labs = 0 (no lab codes in Observation) →
    # labs live in this view. TestItemCode_Code being LOINC is not verified yet: tests outside LOINC_LAB are
    # dropped and reported (the "glycaemic-looking tests (dropped)" list shows locally coded HbA1c / glucose).
    # Optional: if C2 / C3 lack the view or SELECT permission (like C1 Encounter), that cohort is skipped.
    "lab_results": {
        "file": "lab_results.csv", "table": "{schema}.LabResultItem", "kind": "lab_results",
        "optional": True,
        "columns": {"patient_id": "Patient", "code": "TestItemCode_Code", "value": "ResultValue",
                    "date": "ResultDate"},
        "optional_columns": {"test_name": "TestItemCode_Description", "unit": "ResultValueUnits"},
        # VM ingest 1.2.1 (2026-11-19): labs "missing required value" ERROR (C1 < 10, C2 11 rows) = rows with an empty
        # ResultValue; they carry nothing → dropped and counted per code, as for Observation.
        "drop_empty": ["value"],
    },
    "social_history": {
        "file": "social_history.csv", "table": "{schema}.SocialHistory", "kind": "smoking",
        "columns": {"patient_id": "Patient", "value": "SocialHabitQty_Description", "date": "EnteredOn"},
        "optional_columns": {"item": ["SocialHabitCategory_Code", "SocialHabitCategory_Description"]},
        # Items (C1 ingest, 2026-11-19): ALCOHOL, Beverages, Cigarettes, "Cigarettes,Cigars", Cigars, Other,
        # Smoking, Unknown. Smoking = tobacco-smoking items; "Tobacco" for the dry-run data and a possible C2 name.
        # [DECISION PENDING] D7 — "Other" (may be shisha / midwakh) and "Unknown" are left out; medical team.
        # If the filter removes every row of a cohort, ingest stops and prints the items found in the source.
        "filter": {"item": ["Smoking", "Cigarettes", "Cigars", "Cigarettes,Cigars", "Tobacco"]},
    },
    "family_history": {
        "file": "family_history.csv", "table": "{schema}.FamilyHistory",
        "kind": "family_history",
        "columns": {"patient_id": "Patient", "date": "EnteredOn"},
        "optional_columns": {"condition": "Diagnosis_Code", "condition_text": "Diagnosis_Description",
                             "relation": "FamilyMember_Description"},
    },
    "medications": {
        "file": "medications.csv", "table": "{schema}.Medication", "kind": "medications",
        "columns": {"patient_id": "Patient", "date": "FromTime"},
        # atc_code ← DrugProduct_Code: ATC or DDC product / scientific code (C1, C2); absent in C3 → name
        # (DrugProduct_Description)
        "optional_columns": {"atc_code": "DrugProduct_Code", "drug_name": "DrugProduct_Description",
                             "route": "Route_Description"},
    },
    "encounters": {
        "file": "encounters.csv", "table": "{schema}.Encounter", "kind": "encounters",
        "optional": True,
        "columns": {"patient_id": "Patient", "date": "EncounterStartDate"},
        "optional_columns": {"encounter_id": "ID", "encounter_type": "EncounterType"},
    },
}

SEX_MAP = {"M": "Male", "MALE": "Male", "1": "Male", "F": "Female", "FEMALE": "Female", "2": "Female"}

# Smoking value (lower-case text or SNOMED code) → canonical value. Text is tried first, then the code.
# "yes" / "no" are meaningful only if the source (or filter) is specific to smoking.
# NABIDH SocialHabitQty (C1 / C2 ingest, 2026-11-19): low / medium / high = intensity → light / moderate / heavy.
# occasional / rare (not daily, < 10 / day) → light [DECISION PENDING] D7; alternative: current (→ D7 category).
# "other" not mapped (C1 428, C2 306, C3 531 rows): may be other tobacco (shisha / midwakh?) → counted as missing, D7.
SMOKING_VALUES = {
    **{k: "never" for k in ["never", "never smoker", "never smoked", "never smoked tobacco", "non-smoker",
                            "non smoker", "nonsmoker", "non", "no", "lifetime non-smoker"]},
    **{k: "ex" for k in ["ex", "ex-smoker", "ex smoker", "former", "former smoker", "past smoker", "quit",
                         "quit smoking", "stopped smoking"]},
    **{k: "current" for k in ["current", "smoker", "current smoker", "yes", "current every day smoker",
                              "current some day smoker", "every day smoker", "some day smoker",
                              "smoker, current status unknown"]},
    **{k: "light" for k in ["light", "light smoker", "light tobacco smoker", "low",
                            "occasional", "occasional smoker", "rare"]},
    **{k: "moderate" for k in ["moderate", "moderate smoker", "medium"]},
    **{k: "heavy" for k in ["heavy", "heavy smoker", "heavy tobacco smoker", "high"]},
    **{k: "unknown" for k in ["unknown", "unknown if ever smoked", "not asked", "declined", "not known"]},
    # SNOMED (ONC smoking status value set)
    "266919005": "never",           # Never smoked tobacco
    "8517006": "ex",                # Ex-smoker
    "449868002": "current",         # Smokes tobacco daily
    "428041000124106": "current",   # Occasional tobacco smoker
    "77176002": "current",          # Smoker (current status unknown)
    "428061000124105": "light",     # Light tobacco smoker
    "428071000124103": "heavy",     # Heavy tobacco smoker
    "266927001": "unknown",         # Tobacco smoking consumption unknown
}

# Family history status value → positive / negative / unknown
FH_STATUS_VALUES = {
    **{k: "positive" for k in ["yes", "y", "true", "1", "positive", "pos", "present", "confirmed"]},
    **{k: "negative" for k in ["no", "n", "false", "0", "negative", "neg", "absent", "none", "denied",
                               "not present", "no known family history"]},
    **{k: "unknown" for k in ["unknown", "not known", "not asked", "unsure", "declined"]},
}
# Relationship → degree. QDiabetes and LRS count first-degree relatives (mother, father, sibling, child).
# Second degree → positive_non_first_degree (recorded, not counted positive). Empty / unknown relationship → positive.
# NABIDH FamilyMember_Description (VM checks, 2026-11-20): Father, Mother, Brother, Sister, Child, Parent (C1 ≥ 10
# patients; C2 the same without Parent) — all here; the rest (C1 5, C2 4 values in < 10 patients) unseen. A value not
# in the dictionary is decided by its words (FH_TEXT_SECOND_DEGREE / FH_TEXT_FIRST_DEGREE, as for the text).
FH_RELATION_DEGREE = {
    **{k: "first" for k in ["mother", "father", "parent", "parents", "brother", "sister", "sibling", "siblings",
                            "son", "daughter", "child", "children", "first degree", "first-degree",
                            "1st degree relative", "first degree relative", "first-degree relative"]},
    **{k: "other" for k in ["grandmother", "grandfather", "grandparent", "aunt", "uncle", "cousin",
                            "niece", "nephew", "grandchild", "second degree", "second-degree",
                            "2nd degree relative", "second degree relative", "3rd degree relative"]},
}
FH_DIABETES_SNOMED = {"160303001", "73211009", "44054006", "46635009"}
# Description text (NABIDH FamilyHistory.Diagnosis_Description, 2026-11-19): there is no status column; a negative
# record is in the text ("No History Of Diabetes mellitus type 2 (disorder)") → negative. If the text names a
# second-degree relative ("Maternal aunt and uncle have Diabetes mellitus", FamilyMember = Parent) the text wins.
FH_DIABETES_TEXT = re.compile(r"diabet|\b(?:t[12])?dm\b", re.IGNORECASE)
FH_PREDIABETES_SNOMED = {"714628002", "9414007"}       # Prediabetes; impaired glucose tolerance
FH_PREDIABETES_TEXT = re.compile(r"\bpre[- ]?diabet|\bimpaired (?:fasting )?glucose|\bborderline diabet",
                                 re.IGNORECASE)
FH_NEGATION = re.compile(r"^\s*(?:no|nil|none|denies|denied|negative)\b|\bno (?:known )?(?:family )?history\b"
                         r"|\bnegative for\b|\bdenies\b|\bnon[- ]?diabet", re.IGNORECASE)
FH_TEXT_SECOND_DEGREE = re.compile(r"\b(?:aunts?|uncles?|grand\w*|cousins?|nieces?|nephews?)\b", re.IGNORECASE)
FH_TEXT_FIRST_DEGREE = re.compile(r"\b(?:mother|father|parents?|brothers?|sisters?|siblings?|sons?|daughters?)\b",
                                  re.IGNORECASE)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _norm_text(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.lower()


def norm_code_system(s: pd.Series) -> pd.Series:
    """HL7 / FHIR / free-text code system names → ICD-10 / SNOMED / LOINC / ATC."""
    u = s.astype("string").str.strip().str.upper()
    out = u.copy()
    out[u.str.contains("ICD", na=False) | u.isin(["I10", "I10C", "I10CM"])] = "ICD-10"
    out[u.str.contains("SNOMED", na=False) | u.isin(["SCT", "SNM", "SNOMEDCT"])] = "SNOMED"
    out[u.str.contains("LOINC", na=False) | u.isin(["LN"])] = "LOINC"
    out[u.str.contains("ATC", na=False)] = "ATC"
    return out


def _value_counts(source: str, field: str, s: pd.Series, top: int = 50) -> list[dict]:
    vc = s.astype("string").fillna("<missing>").str.slice(0, 80).value_counts().head(top)
    return [{"source": source, "field": field, "value": str(k), "n_rows": int(v)} for k, v in vc.items()]


def _labels(s: pd.Series, top: int = 15, k: int = 10) -> str:
    """Category labels (e.g. SocialHistory item) and row counts; a label with < k rows is not printed by name."""
    vc = s.astype("string").fillna("<empty>").str.slice(0, 40).value_counts()
    big, small = vc[vc >= k], vc[vc < k]
    out = ", ".join(f"{v} ({n})" for v, n in big.head(top).items())
    if len(big) > top:
        out += f", +{len(big) - top} labels"
    if len(small):
        out += f"{', ' if out else ''}+{len(small)} labels < {k} rows"
    return out or "none"


def alternatives(src) -> list[str]:
    """Source column definition (a name or a list of names) → candidate names."""
    return [src] if isinstance(src, str) else list(src)


def resolve_column(src, available) -> str | None:
    """Source column definition → the first candidate found in `available` (None if none)."""
    have = set(available)
    return next((c for c in alternatives(src) if c in have), None)


def label(src) -> str:
    return " | ".join(alternatives(src))


def filter_columns(spec: dict) -> dict:
    """filter key → source column definition. A canonical-name key (e.g. "item") means that name's source column."""
    names = {**spec.get("optional_columns", {}), **spec["columns"]}
    return {key: names.get(key, key) for key in (spec.get("filter") or {})}


def _select(df: pd.DataFrame, spec: dict, name: str, where: str | None = None) -> tuple[pd.DataFrame, dict]:
    cols, opt = spec["columns"], spec.get("optional_columns", {})
    got = {canon: resolve_column(src, df.columns) for canon, src in cols.items()}
    missing = [label(cols[c]) for c, src in got.items() if src is None]
    if missing:
        raise KeyError(f"{name} ({where or spec.get('file')}): required columns missing in the source: {missing}. "
                       f"Available: {list(df.columns)}")
    info = {"rows_read": int(len(df))}
    for key, fsrc in filter_columns(spec).items():
        src = resolve_column(fsrc, df.columns)
        if src is None:
            raise KeyError(f"{name}: filter column missing: {label(fsrc)}")
        allowed = spec["filter"][key]
        keep = _norm_text(df[src]).isin([a.lower() for a in allowed]).fillna(False).astype(bool)
        info[f"filtered_out_by_{key}"] = int((~keep).sum())
        if len(df) and not keep.any():
            raise ValueError(f"{name}: filter {key} = {allowed} removed every row. Values in the source: "
                             f"{_labels(df[src])}. Update SOURCES['{name}']['filter'].")
        if (~keep).any():
            info[f"filtered_out_values_{key}"] = _labels(df.loc[~keep, src])
        df = df[keep]
    out = pd.DataFrame({canon: df[src] for canon, src in got.items()})
    opt_got = {canon: resolve_column(src, df.columns) for canon, src in opt.items()}
    info["absent_optional_columns"] = [c for c, src in opt_got.items() if src is None]
    for canon, src in opt_got.items():
        if src is not None:
            out[canon] = df[src]
    for k, v in spec.get("constants", {}).items():
        out[k] = out[k].fillna(v) if k in out else v
    for col in spec.get("drop_empty", []):
        txt = out[col].astype("string").str.strip()
        empty = (txt.isna() | txt.eq("") | txt.str.upper().eq("NULL")).fillna(True).astype(bool)   # "NULL" as text
        tokens = [str(t) for t in spec.get("empty_values", {}).get(col, [])]
        placeholder = pd.Series(False, index=out.index)
        if tokens:
            as_num = pd.to_numeric(pd.Series(tokens), errors="coerce").dropna()
            placeholder = ((txt.str.lower().isin([t.lower() for t in tokens])
                            | pd.to_numeric(txt, errors="coerce").isin(as_num)).fillna(False).astype(bool) & ~empty)
            empty |= placeholder
        info[f"dropped_empty_{col}"] = int(empty.sum())
        if tokens:
            info[f"dropped_empty_{col}_placeholder"] = int(placeholder.sum())
        if empty.any() and "code" in out:
            info[f"dropped_empty_{col}_by_code"] = _labels(out.loc[empty, "code"].astype("string").str.strip())
        out = out[~empty]
    return out, info


def _parse_dates(df: pd.DataFrame, spec: dict, info: dict) -> pd.DataFrame:
    fmt = spec.get("date_format", DATE_FORMAT)
    for col in ("date", "date_of_birth"):
        if col not in df:
            continue
        raw = df[col].astype("string").str.strip()
        if fmt == "horolog":
            parsed = parse_horolog(raw)
        elif fmt:
            parsed = pd.to_datetime(raw, format=fmt, errors="coerce")
        else:
            parsed = pd.to_datetime(raw, errors="coerce")
        info[f"unparseable_{col}"] = int((parsed.isna() & raw.notna() & (raw != "")).sum())
        df[col] = parsed
    return df


def parse_horolog(raw: pd.Series) -> pd.Series:
    """IRIS internal date ($HOROLOG): "day" or "day,seconds" (day 0 = 1840-12-31) → datetime."""
    parts = raw.astype("string").str.strip().str.split(",", n=1)
    day = pd.to_numeric(parts.str[0], errors="coerce")
    sec = pd.to_numeric(parts.str[1], errors="coerce").fillna(0)
    day = day.where(day.isna() | (day == day.round()))          # fractional day = invalid
    out = HOROLOG_EPOCH + pd.to_timedelta(day, unit="D") + pd.to_timedelta(sec, unit="s")
    return pd.Series(out, index=raw.index)


def _fh_diabetes(df: pd.DataFrame, cond_cols: list[str]) -> tuple[pd.Series, pd.Series]:
    """Is the family history record diabetes? → (how recognised: "ICD-10 code" / "SNOMED code" / "text only" / NA,
    is prediabetes). Code first: ICD-10 E08–E14 / Z83.3, diabetes SNOMED. If the code is none of these (local
    number, text written into the code column), the text: "diabet", "DM". Prediabetes (R73, SNOMED 714628002 /
    9414007, text) does not count as a diabetes family history. NABIDH C1 FamilyHistory.Diagnosis_Code
    (2026-11-19): ~62% SNOMED / ICD-10, ~20% text in the code column ("DIABETES"), ~17% local number."""
    icd = pd.Series(False, index=df.index)
    snomed = pd.Series(False, index=df.index)
    text = pd.Series(False, index=df.index)
    pre = pd.Series(False, index=df.index)
    for c in cond_cols:
        raw = df[c].astype("string").str.strip()
        code = raw.str.upper().str.replace(r"[.\s]", "", regex=True)
        icd |= (code.str.match(r"^(?:E0[89]|E1[0-4])", na=False) | code.str.startswith("Z833", na=False)).astype(bool)
        snomed |= raw.isin(FH_DIABETES_SNOMED).fillna(False).astype(bool)
        text |= raw.str.contains(FH_DIABETES_TEXT, na=False).astype(bool)
        pre |= (code.str.startswith("R73", na=False) | raw.isin(FH_PREDIABETES_SNOMED)
                | raw.str.contains(FH_PREDIABETES_TEXT, na=False)).fillna(False).astype(bool)
    how = pd.Series(pd.NA, index=df.index, dtype=object)
    how[text] = "text only"
    how[snomed] = "SNOMED code"
    how[icd] = "ICD-10 code"
    how[pre] = pd.NA
    return how, pre


# --------------------------------------------------------------------------
# Source kind handlers: (df, name, vc) → {canonical_table: df}
# --------------------------------------------------------------------------
def dob_from_age(age: pd.Series, reference=AGE_REFERENCE_DATE) -> pd.Series:
    """Age in whole years → approximate date of birth: reference − (age + 0.5) years. Not 0–120 / not a number → NaT."""
    a = pd.to_numeric(age.astype("string").str.strip(), errors="coerce")
    a = a.where((a >= 0) & (a <= 120))
    out = pd.Timestamp(reference) - pd.to_timedelta((a + 0.5) * 365.25, unit="D")
    return pd.Series(out, index=age.index).dt.normalize()


def _h_patients(df, name, vc):
    vc += _value_counts(name, "sex", df["sex"])
    for col in ("nationality", "ethnicity_raw"):
        if col in df:
            vc += _value_counts(name, col, df[col], top=200)
    raw_sex = df["sex"].astype("string").str.strip()
    df["sex"] = raw_sex.str.upper().map(SEX_MAP).fillna(raw_sex)
    if "age" in df:
        derived = dob_from_age(df["age"], AGE_REFERENCE_DATE)
        given = df["date_of_birth"] if "date_of_birth" in df else pd.Series(pd.NaT, index=df.index)
        use = given.isna() & derived.notna()
        bad_age = df["age"].notna() & derived.isna()
        vc.append({"source": name, "field": "date_of_birth",
                   "value": f"derived from Age at {AGE_REFERENCE_DATE} (mid-year)", "n_rows": int(use.sum())})
        if bad_age.any():
            vc += _value_counts(name, "age not usable (non-numeric or outside 0-120)", df.loc[bad_age, "age"], top=20)
        df["date_of_birth"] = given.where(~use, derived)
    return {"patients": df}


def split_dx_codes(code: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Diagnosis_Code cell → (one code per element, as a list; cell had a trailing dot; number of codes in the cell).
    NABIDH Diagnosis_Code (VM checks, 2026-11-20) is ICD-10-CM with dots ("E11.9", "R73.03", "E11.3393"); a few C1
    cells end in a dot ("E11.9.") and a few C2 cells hold 2–3 codes ("E11.9, I10"). Matching (codelists.norm_icd)
    ignores dots but reads only the start of the cell, so a second code was lost → split on comma, strip the dot."""
    raw = code.astype("string").str.strip()
    trailing = raw.str.contains(r"\.(?:\s*,|$)", regex=True).fillna(False).astype(bool)
    parts = raw.str.split(r"\s*,\s*", regex=True)
    parts = parts.map(lambda p: p if not isinstance(p, list) else
                      ([c.rstrip(".").strip() for c in p if c.rstrip(".").strip()] or [pd.NA]))
    n = parts.map(lambda p: len(p) if isinstance(p, list) else 1)
    return parts, trailing, n


def _h_conditions(df, name, vc):
    vc += _value_counts(name, "code_system", df["code_system"])
    df["code_system"] = norm_code_system(df["code_system"])
    parts, trailing, n = split_dx_codes(df["code"])
    if trailing.any():
        vc.append({"source": name, "field": "code: trailing dot removed", "value": "<n rows>",
                   "n_rows": int(trailing.sum())})
    if (n > 1).any():
        vc += _value_counts(name, "code cell with several codes → one row each",
                            n[n > 1].astype(str) + " codes in the cell")
    df = df.assign(code=parts).explode("code").reset_index(drop=True)
    df["code"] = df["code"].astype("string")
    return {"conditions": df}


def split_measurements(m: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Splits a single measurement table into labs and observations by LOINC."""
    code = m["code"].astype("string").str.strip()
    system = norm_code_system(m["code_system"]) if "code_system" in m else pd.Series("LOINC", index=m.index)
    is_lab = code.isin(list(codelists.LOINC_LAB)).fillna(False).astype(bool)
    labs = m[is_lab].assign(code=code[is_lab]).rename(columns={"code": "loinc"})
    obs = m[~is_lab].assign(code=code[~is_lab], code_system=system[~is_lab])
    keys = list(zip(obs["code_system"].astype(str), obs["code"].astype(str)))
    obs["concept"] = [codelists.OBS_CODE_TO_CONCEPT.get(k, f"unmapped:{k[1]}") for k in keys]
    return labs, obs


# Vitals (Observation 8302-2 height, 3141-9 weight, 39156-5 BMI) have no unit column (i32): the value distribution per
# vital (as for labs, only in groups of ≥ LAB_STATS_MIN_PATIENTS patients) shows the unit in the ingest block. Expected:
# height ~150–180 cm (~1.5–1.8 would be metres), weight ~60–100 kg, BMI ~25–32 kg/m².
VITAL_CONCEPTS = ["height_cm", "weight_kg", "bmi"]
# VM checks (2026-11-20): height is in cm (median C1 163.5 / C2 167), but a few values are shaped 9.99 / 9.999 (~0.4%
# of C1 rows) = metres. A height of 1.2–2.3 can only be metres → × 100 (counted); other values are left as they are
# (phenotype keeps 120–230 cm).
HEIGHT_METRES = (1.2, 2.3)


def _h_measurements(df, name, vc):
    unit = df["unit"] if "unit" in df else pd.Series(pd.NA, index=df.index)
    vc += _value_counts(name, "code | unit", df["code"].astype("string") + " | " + unit.astype("string").fillna(""),
                        top=100)
    labs, obs = split_measurements(df)
    vc += _value_counts(name, "lab value non-numeric (raw)",
                        labs.loc[pd.to_numeric(labs["value"], errors="coerce").isna() & labs["value"].notna(), "value"],
                        top=20)
    v = pd.to_numeric(obs["value"], errors="coerce")
    metres = (obs["concept"].eq("height_cm") & v.between(*HEIGHT_METRES)).fillna(False).astype(bool)
    if metres.any():
        obs.loc[metres, "value"] = (v[metres] * 100).round(1).map("{:g}".format)
        vc.append({"source": name, "field": "height in metres → cm (1.2–2.3 × 100)", "value": "<n rows>",
                   "n_rows": int(metres.sum())})
    vit = obs[obs["concept"].isin(VITAL_CONCEPTS).fillna(False).astype(bool)]
    vit_unit = vit["unit"] if "unit" in vit else pd.Series(pd.NA, index=vit.index, dtype="string")
    vc += [{"source": name, "field": "vital value by concept | unit", "value": label, "n_rows": n}
           for label, n in lab_value_stats(vit, vit["concept"], vit_unit)]
    return {"labs": labs, "observations": obs}


# Tests with a code outside LOINC_LAB but a glycaemic-looking name (locally coded HbA1c / glucose) are listed apart.
GLYCAEMIC_NAME = re.compile(r"a1c|glyc|gluc|ogtt|sugar", re.IGNORECASE)
# Rows that carry a study code but whose name says another test (C1 LabResultItem, 2026-11-19) are dropped:
#   4548-4 + "EAG (ESTIMATED AVERAGE GLUCOSE)": mean glucose in mg/dL; read as HbA1c it is ~140% → false DM evidence
#   1558-6 + "BLOOD SUGAR -RBS" / "GLUCOSE (RANDOM)": random, not fasting, glucose
# 1521-4 + "GLUCOSE POST PRANDIAL (PPBS)" / "POSTPRANDIAL BLOOD SUGAR - 2 HRS" are kept (not OGTT; medical team).
LAB_EAG_NAME = re.compile(r"\beag\b|estimated average glucose", re.IGNORECASE)
LAB_RANDOM_NAME = re.compile(r"\brbs\b|random", re.IGNORECASE)
LAB_STATS_MIN_PATIENTS = 10                         # value distribution only in kind | unit groups of ≥ 10 patients
# Plausible value range — report only: the value is kept and counts towards status (exclusion is the medical
# team's call, K11). Without a unit % / mg/dL is assumed (phenotype.glycaemic_events); a unitless mmol/mol HbA1c
# (e.g. 48) or mmol/L glucose (e.g. 6.1) shows up here as out of range.
LAB_PLAUSIBLE = {"hba1c %": (3, 20), "hba1c mmol/mol": (10, 200), "glucose mg/dL": (20, 1000),
                 "glucose mmol/L": (1, 55)}
# Unit spelling (VM ingest 1.2.1, 2026-11-19): the same unit arrives in several spellings (mg/dL, MG/DL, mg/dl) and
# HbA1c also has "0" and "NULL" as unit; that alone gave the schema WARN "multiple units per LOINC" (1521-4, 1558-6,
# 4548-4). Key = lower case without spaces → one spelling; a placeholder → no unit (% / mg/dL assumed, as before).
# A unit not listed here is kept as delivered (stripped), so a really different unit still gives the WARN.
LAB_UNITS = {"%": "%", "mg/dl": "mg/dL", "mmol/l": "mmol/L", "mmol/mol": "mmol/mol"}
LAB_UNIT_EMPTY = {"0", "null", "none", "na", "n/a", "-"}


def norm_lab_unit(unit: pd.Series) -> pd.Series:
    """Delivered lab unit → canonical spelling (LAB_UNITS): case, whitespace (incl. non-breaking space) and Unicode
    look-alikes (NFKC) do not matter; empty or a placeholder (LAB_UNIT_EMPTY) → NA."""
    raw = unit.astype("string").str.strip()
    key = raw.str.normalize("NFKC").str.lower().str.replace(r"\s+", "", regex=True)   # NFKC: "％" → "%", NBSP → " "
    out = key.map(LAB_UNITS).astype("string").fillna(raw)
    return out.mask((key.isin(LAB_UNIT_EMPTY) | key.eq("")).fillna(False).astype(bool))


# Lab result text. VM ingest 1.3.0 (2026-11-20): after the empty values were dropped, labs "missing required value"
# was still C1 < 10 / C2 10 rows = results that are not a plain number. A decimal comma ("6,2"; 1–2 decimals, so not a
# thousands separator) is read as a point. Anything else that is not a finite number ("<5.0", ">14", text) is dropped
# and counted by kind | shape (explore.shape: a digit → 9, letters → a; no value shows). A comparator is not read as
# its bound: "<5.7" is a normal HbA1c, its bound 5.7 is prediabetes — whether such results count is the medical
# team's call.
LAB_DECIMAL_COMMA = re.compile(r"^[+-]?\d+,\d{1,2}$")


def parse_lab_value(raw: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Lab result text → (number as text, how: "number" / "decimal comma" / NA = not a finite number).
    Whitespace incl. non-breaking space is ignored (NFKC + strip)."""
    txt = raw.astype("string").str.normalize("NFKC").str.strip()
    comma = txt.str.match(LAB_DECIMAL_COMMA).fillna(False).astype(bool)
    out = txt.where(~comma, txt.str.replace(",", ".", regex=False))
    num = pd.to_numeric(out, errors="coerce")
    ok = (num.notna() & (num.abs() != float("inf"))).fillna(False).astype(bool)
    how = pd.Series(pd.NA, index=raw.index, dtype=object)
    how[ok] = "number"
    how[ok & comma] = "decimal comma"
    return out.where(ok), how


def lab_range_class(kind: pd.Series, unit: pd.Series) -> pd.Series:
    """Kind + unit → LAB_PLAUSIBLE key (same unit rule as phenotype.glycaemic_events)."""
    u = unit.astype("string").str.lower().fillna("")
    a1c = kind.isin(["hba1c", "hba1c_ifcc"]).fillna(False).astype(bool)
    out = pd.Series("glucose mg/dL", index=kind.index, dtype=object)
    out[~a1c & u.str.contains("mmol/l").astype(bool)] = "glucose mmol/L"
    out[a1c] = "hba1c %"
    out[a1c & (kind.eq("hba1c_ifcc") | u.str.contains("mmol/mol")).fillna(False).astype(bool)] = "hba1c mmol/mol"
    return out


def lab_value_stats(labs: pd.DataFrame, kind: pd.Series, unit: pd.Series) -> list[tuple[str, int]]:
    """Numeric value distribution per kind | unit (unit check, K11) → [(label, row count)], e.g.
    "hba1c | % : 812 patients, p5 5.2 / median 6.9 / p95 10.1". No distribution is printed for a group with
    < LAB_STATS_MIN_PATIENTS patients (so no single patient's values show)."""
    g = pd.DataFrame({"kind": kind.astype("string").fillna("?"), "unit": unit.astype("string").fillna("<no unit>"),
                      "pid": labs["patient_id"], "v": pd.to_numeric(labs["value"], errors="coerce")})
    out = []
    for (k, u), x in g.groupby(["kind", "unit"], sort=True):
        n_pat = x.loc[x["v"].notna(), "pid"].nunique()
        if n_pat < LAB_STATS_MIN_PATIENTS:
            label = f"{k} | {u} : < {LAB_STATS_MIN_PATIENTS} patients with a numeric value, no distribution"
        else:
            p5, p50, p95 = x["v"].quantile([0.05, 0.5, 0.95])
            label = f"{k} | {u} : {n_pat} patients, p5 {p5:.3g} / median {p50:.3g} / p95 {p95:.3g}"
        out.append((label, int(len(x))))
    return out


def _h_lab_results(df, name, vc):
    """Lab view (NABIDH LabResultItem): only the study's glycaemic labs (codelists.LOINC_LAB) → labs. Other tests
    (cholesterol, blood count …) are dropped; they are not observations. Report: kept and dropped code | unit | name,
    dropped tests whose name looks glycaemic, value distribution per kind | unit (unit → phenotype.glycaemic_events
    conversion) and the number of values outside the plausible range (LAB_PLAUSIBLE; report only)."""
    empty = pd.Series(pd.NA, index=df.index, dtype="string")
    code = df["code"].astype("string").str.strip()
    test = (df["test_name"] if "test_name" in df else empty).astype("string").str.strip()
    raw_unit = (df["unit"] if "unit" in df else empty).astype("string").str.strip()
    unit = norm_lab_unit(raw_unit)
    kind = code.map(codelists.LOINC_LAB)
    in_list = kind.notna().astype(bool)
    txt = test.fillna("")
    other_by_name = ((kind.eq("hba1c") & txt.str.contains(LAB_EAG_NAME))
                     | (kind.eq("fpg") & txt.str.contains(LAB_RANDOM_NAME))).fillna(False).astype(bool)
    keep = in_list & ~other_by_name
    shown = code.fillna("<empty>") + " | " + unit.fillna("") + " | " + test.fillna("")   # name last: cut at 80 chars
    vc += _value_counts(name, "study lab: code | unit | name", shown[keep], top=40)
    vc += _value_counts(name, "study lab unit: delivered → canonical",
                        raw_unit[keep].fillna("<empty>").replace("", "<empty>") + " → " + unit[keep].fillna("<no unit>"))
    if other_by_name.any():
        vc += _value_counts(name, "study code, other test by name (dropped): code | unit | name", shown[other_by_name])
        vc.append({"source": name, "field": "rows dropped: study code, other test by name", "value": "<n rows>",
                   "n_rows": int(other_by_name.sum())})
    look = ~in_list & txt.str.contains(GLYCAEMIC_NAME).astype(bool)
    vc += _value_counts(name, "glycaemic-looking tests (dropped): code | unit | name", shown[look], top=40)
    vc += _value_counts(name, "other tests (dropped): code | unit | name", shown[~in_list & ~look], top=60)
    if (~in_list).any():
        vc.append({"source": name, "field": "rows dropped: not a study lab", "value": "<n rows>",
                   "n_rows": int((~in_list).sum())})
    labs = df[keep].assign(code=code[keep], unit=unit[keep]).rename(columns={"code": "loinc"})
    value, how = parse_lab_value(labs["value"])
    bad = how.isna()
    vc += _value_counts(name, "lab value non-numeric (raw)", labs.loc[bad, "value"], top=20)
    if how.eq("decimal comma").any():
        vc.append({"source": name, "field": "lab value: decimal comma read as point", "value": "<n rows>",
                   "n_rows": int(how.eq("decimal comma").sum())})
    if bad.any():
        raw = labs.loc[bad, "value"].astype("string").fillna("")
        shp = kind.loc[raw.index].astype(str) + " | " + raw.map(lambda x: explore.shape(x) if x else "<empty>")
        vc += _value_counts(name, "non-numeric value (dropped): kind | shape", shp, top=20)
        vc.append({"source": name, "field": "rows dropped: non-numeric value", "value": "<n rows>",
                   "n_rows": int(bad.sum())})
    labs = labs.assign(value=value)[~bad]
    k_kind, k_unit = kind.loc[labs.index], labs["unit"]
    vc += [{"source": name, "field": "value by kind | unit", "value": label, "n_rows": n}
           for label, n in lab_value_stats(labs, k_kind, k_unit)]
    rng = lab_range_class(k_kind, k_unit)
    v = pd.to_numeric(labs["value"], errors="coerce")
    lo, hi = rng.map(lambda r: LAB_PLAUSIBLE[r][0]), rng.map(lambda r: LAB_PLAUSIBLE[r][1])
    outside = (v.notna() & ((v < lo) | (v > hi))).astype(bool)
    label = (k_kind.astype(str) + " | " + k_unit.fillna("<no unit>").astype(str) + " : outside "
             + lo.astype(str) + "–" + hi.astype(str) + " " + rng.str.split(" ").str[1] + " (kept)")
    vc += _value_counts(name, "value outside plausible range", label[outside], top=20)
    return {"labs": labs}


def _h_smoking(df, name, vc, item_filtered: bool = False):
    """item_filtered: SOURCES has an item filter → every selected item counts as smoking. Otherwise, if several
    items (e.g. smoking + alcohol) are seen, it stops: which item is smoking is unknown."""
    if "item" in df and not item_filtered and df["item"].nunique(dropna=True) > 1:
        raise ValueError(f"{name}: SocialHistory holds several items "
                         f"({sorted(df['item'].dropna().unique())[:10]}). "
                         f"Select the smoking item with SOURCES['{name}']['filter'].")
    if "item" in df:
        vc += _value_counts(name, "item", df["item"])
    key = _norm_text(df["value"])
    mapped = key.map(SMOKING_VALUES)
    code = df["code"].astype("string").str.strip() if "code" in df else pd.Series(pd.NA, index=df.index, dtype="string")
    mapped = mapped.fillna(code.map(SMOKING_VALUES))
    has_any = key.notna() | code.notna()
    value = mapped.astype(object).where(mapped.notna(), "unmapped:" + key.fillna(code).astype(object).astype(str))
    shown = key.fillna("<empty>").astype(str) + " → " + value.astype(str)
    if "item" in df:                                # with several items: which item the value came from
        shown = df["item"].astype("string").fillna("<empty>").astype(str) + " | " + shown
    vc += _value_counts(name, "value → canonical", shown)
    out = pd.DataFrame({"patient_id": df["patient_id"], "concept": "smoking_status",
                        "code_system": code.where(code.isna(), "SNOMED"), "code": code,
                        "value": value, "unit": pd.NA, "date": df["date"]})[has_any]
    return {"observations": out}


def _h_family_history(df, name, vc):
    cond_cols = [c for c in ("condition", "condition_text") if c in df]
    if cond_cols:                                   # diabetes record: the code (ICD-10 / SNOMED), else the text, says so
        how, pre = _fh_diabetes(df, cond_cols)
        is_dm = how.notna()
        shown = df[cond_cols].astype("string").fillna("").agg(" | ".join, axis=1)
        vc += _value_counts(name, "diabetes recognised by", how[is_dm])
        if "condition" in df:                       # codes that only the text recognised (local numbers, "Diabetes")
            vc += _value_counts(name, "text only: Diagnosis_Code", df.loc[how.eq("text only").fillna(False)
                                                                          .astype(bool), "condition"], top=20)
        vc += _value_counts(name, f"{' | '.join(cond_cols)} (non-diabetes, dropped)", shown[~is_dm & ~pre], top=30)
        vc += _value_counts(name, f"{' | '.join(cond_cols)} (prediabetes, dropped)", shown[pre], top=20)
        df = df[is_dm]
    if "status" in df:
        raw = _norm_text(df["status"])
        st = raw.map(FH_STATUS_VALUES)
        value = st.astype(object).where(st.notna(), "unmapped:" + raw.astype(object).astype(str))
        value = value.where(raw.notna(), "unknown")
        vc += _value_counts(name, "status → canonical", raw.fillna("<empty>").astype(str) + " → " + value.astype(str))
    else:
        value = pd.Series("positive", index=df.index, dtype=object)
    text = df["condition_text"].astype("string") if "condition_text" in df else pd.Series(pd.NA, index=df.index,
                                                                                          dtype="string")
    negated = text.str.contains(FH_NEGATION, na=False).astype(bool) & (value == "positive")
    if negated.any():
        vc += _value_counts(name, "condition_text negated → negative", text[negated], top=20)
        value = value.where(~negated, "negative")
    second = (text.str.contains(FH_TEXT_SECOND_DEGREE, na=False)
              & ~text.str.contains(FH_TEXT_FIRST_DEGREE, na=False)).astype(bool)
    if second.any():
        vc += _value_counts(name, "second-degree relative in text", text[second], top=20)
    if "relation" in df:
        rel = _norm_text(df["relation"])
        deg = rel.map(FH_RELATION_DEGREE)
        # Not in the dictionary: the words decide, as in the text ("paternal grandmother", "maternal aunt" → other;
        # "grandmother and mother" → first); none of them → treated as first, as before
        by_word = deg.isna() & rel.notna()
        w2 = rel.str.contains(FH_TEXT_SECOND_DEGREE, na=False).astype(bool)
        w1 = rel.str.contains(FH_TEXT_FIRST_DEGREE, na=False).astype(bool)
        deg = deg.where(~(by_word & w1), "first").where(~(by_word & w2 & ~w1), "other")
        by_word &= deg.notna()
        label = deg.astype(object).where(~by_word, (deg.astype("string") + " (by word)").astype(object))
        label = label.where(deg.notna(), "unmapped (treated as first)")
        label = label.where(rel.notna(), "not recorded (treated as first)")
        vc += _value_counts(name, "relation → degree", rel.fillna("<empty>").astype(str) + " → " + label.astype(str))
        second |= deg.eq("other").fillna(False).astype(bool)
    value = value.where(~((value == "positive") & second), "positive_non_first_degree")
    out = pd.DataFrame({"patient_id": df["patient_id"], "concept": "family_history_dm", "code_system": pd.NA,
                        "code": pd.NA, "value": value, "unit": pd.NA, "date": df["date"]})
    return {"observations": out}


ATC_LIKE = re.compile(r"^[A-Z]\d{2}([A-Z]{1,2}\d{0,2})?$")


def _resolve_drug(code, drug, route) -> tuple[str, list[str]]:
    """One drug record → (method, ATC list). An ATC-shaped code as is; a DDC product / scientific code (or its
    6-digit stem) via the DDC reference (a recognised code has the final say); no code or an unrecognised one → from
    the drug name. The all-zero placeholder ("0000-000000-0000", C1 / C2 2026-11-19) counts as no code."""
    if code is not None and ddc.is_placeholder(code):
        code = None
    if code is not None:
        if ATC_LIKE.match(code):
            return "ATC code", [code]
        how, atcs = ddc.lookup_code(code, route)
        if how != "not a DDC code":
            return how, atcs
        if drug is None:
            return "code not ATC/DDC, no name", []
        how, atcs = ddc.lookup_name(drug, route)
        return "code not ATC/DDC → " + how, atcs
    if drug is None:
        return "no code, no name", []
    return ddc.lookup_name(drug, route)


DDC_NO_CLASS = ("DDC: not a study drug class", "DDC: non-systemic route")


def _ddc_no_class_check(code, drug, route) -> tuple[str, list[str]]:
    """A DDC code without a study class: (DDC "ingredients | route", ATC the drug name would give). A non-empty ATC
    means code and name disagree — report only; the code keeps the final say."""
    info = ddc.code_info(code) or "?"
    return info, (ddc.lookup_name(drug, route)[1] if drug is not None else [])


def _h_medications(df, name, vc):
    """Drug → ATC (io/adapters/ddc.py). C1 / C2: DrugProduct_Code = DDC product or scientific code (a few rows carry a
    6-digit stem, a VMP formulary code or the all-zero placeholder); C3: no code, DrugProduct_Description (name) →
    DDC trade name + active ingredient. Combination product → one row per active ingredient. A record outside the
    study drug classes does not enter the canonical table (atc_code is required); how many dropped and why is in
    value_counts, with the DDC active ingredient of the codes without a study class."""
    empty = pd.Series(pd.NA, index=df.index, dtype="string")
    code = (df["atc_code"] if "atc_code" in df else empty).astype("string").str.strip().str.upper().replace("", pd.NA)
    drug = (df["drug_name"] if "drug_name" in df else empty).astype("string").str.strip().replace("", pd.NA)
    route = (df["route"] if "route" in df else empty).astype("string").str.strip().replace("", pd.NA)
    keys = list(zip(*([None if pd.isna(x) else str(x) for x in s] for s in (code, drug, route))))
    cache = {k: _resolve_drug(*k) for k in set(keys)}
    how = pd.Series([cache[k][0] for k in keys], index=df.index, dtype="string")
    atcs = pd.Series([cache[k][1] for k in keys], index=df.index, dtype=object)
    n_atc = atcs.map(len)

    vc += _value_counts(name, "drug → ATC method", how)
    fmt_of = {c: ddc.code_format(c) for c in {k[0] for k in keys}}
    vc += _value_counts(name, "drug code format", pd.Series([fmt_of[k[0]] for k in keys], index=df.index))
    unknown = how.str.startswith("code not ATC/DDC").fillna(False).astype(bool)
    vc += _value_counts(name, "drug code not ATC/DDC", code[unknown], top=30)
    # i22: which DDC products the codes without a study class are (DDC active ingredient | route; reference data),
    # and whether the row's drug name would have given a study class (code and name disagree → listed, not used)
    no_class = how.isin(DDC_NO_CLASS).fillna(False).astype(bool)
    if no_class.any():
        chk = {k: _ddc_no_class_check(*k) for k in {k for k, nc in zip(keys, no_class) if nc}}
        nc_keys = [k for k, nc in zip(keys, no_class) if nc]
        info = pd.Series([chk[k][0] for k in nc_keys], index=df.index[no_class], dtype="string")
        h = how[no_class]
        vc += _value_counts(name, "DDC: not a study drug class (DDC ingredients | route)",
                            info[h.eq("DDC: not a study drug class")], top=30)
        vc += _value_counts(name, "DDC: non-systemic route (DDC ingredients | route | row route)",
                            info[h.eq("DDC: non-systemic route")] + " | row: "
                            + route[no_class & how.eq("DDC: non-systemic route")].fillna("-"), top=20)
        name_atc = pd.Series([chk[k][1] for k in nc_keys], index=df.index[no_class], dtype=object)
        clash = name_atc.map(len) > 0
        vc.append({"source": name, "field": "DDC code without study class, drug name has one", "value": "<n rows>",
                   "n_rows": int(clash.sum())})
        if clash.any():
            shown = (info[clash].str.split(" | ", regex=False).str[0].str.slice(0, 28) + " ≠ "
                     + name_atc[clash].str.join("+") + " ← " + drug[no_class][clash])
            vc += _value_counts(name, "DDC code without study class, drug name has one: DDC ≠ name ATC ← name",
                                shown, top=20)
    by_name = how.str.contains("name: ", regex=False).fillna(False).astype(bool)
    hit = by_name & (n_atc > 0)
    vc += _value_counts(name, "ATC ← drug_name (name match)", atcs[hit].str.join("+") + " ← " + drug[hit], top=50)
    vc += _value_counts(name, "drug_name without study drug class", drug[by_name & (n_atc == 0)], top=50)
    if (n_atc > 1).any():
        vc.append({"source": name, "field": "combination products (rows → several ATC rows)", "value": "<n rows>",
                   "n_rows": int((n_atc > 1).sum())})
    if (n_atc == 0).any():                          # atc_code is required → a record without a class stays out
        vc.append({"source": name, "field": "rows dropped: no study drug class", "value": "<no ATC>",
                   "n_rows": int((n_atc == 0).sum())})
    out = df.assign(atc_code=atcs).explode("atc_code")
    out = out[out["atc_code"].notna()].reset_index(drop=True)
    vc += _value_counts(name, "ATC (3 chars) after mapping", out["atc_code"].astype("string").str.slice(0, 3))
    return {"medications": out}


def _passthrough(table):
    return lambda df, name, vc: {table: df}


HANDLERS = {
    "patients": _h_patients, "conditions": _h_conditions, "measurements": _h_measurements,
    "smoking": _h_smoking, "family_history": _h_family_history, "medications": _h_medications,
    "lab_results": _h_lab_results, "labs": _passthrough("labs"), "observations": _passthrough("observations"),
    "encounters": _passthrough("encounters"),
}


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def load(raw_dir: Path, cohort: str, sources: dict | None = None, progress=None) -> tuple[Dataset, dict]:
    """Raw-file path: reads one cohort folder. Returns (canonical Dataset, report).

    Report: {"input": "files", "sources": {name: {file, rows_read, rows_out, unparseable_*,
            absent_optional_columns, ...}}, "value_counts": [{source, field, value, n_rows}, ...]}
            — for extending the mapping dictionaries.
    """
    raw_dir = Path(raw_dir)

    def read(name: str, spec: dict):
        p = raw_dir / spec["file"]
        if not p.exists():
            if spec.get("optional"):
                return None, {"file": spec["file"], "status": "absent (optional)"}
            raise FileNotFoundError(f"{name}: {p}")
        return read_raw_csv(p, **CSV_OPTIONS), {"file": spec["file"]}

    return _load(cohort, sources or SOURCES, read, "files", progress)


def iris_query(conn, spec: dict, name: str, params: dict) -> str:
    """The source's IRIS query: the full `query`, or a SELECT fetching from `table` only the columns named in the
    mapping (case-insensitive) under the `columns` names."""
    try:
        if spec.get("query"):
            return spec["query"].format(**params)
        table = spec["table"].format(**params)
    except KeyError as e:
        raise KeyError(f"{name}: placeholder {e} not in IRIS_COHORTS (available: {sorted(params)})") from None
    have = iris.column_names(conn, table)
    by_lower = {c.lower(): c for c in have}
    missing = [label(src) for src in spec["columns"].values()
               if not any(c.lower() in by_lower for c in alternatives(src))]
    if missing:
        raise KeyError(f"{name} ({table}): required columns missing in the table: {missing}. Available: {have}")
    wanted = [c for src in [*spec["columns"].values(), *spec.get("optional_columns", {}).values(),
                            *filter_columns(spec).values()] for c in alternatives(src)]
    select = [f"{iris.quote_ident(by_lower[c.lower()])} AS {iris.quote_ident(c)}"
              for c in dict.fromkeys(wanted) if c.lower() in by_lower]
    return f"SELECT {', '.join(select)} FROM {table}"


# While a query streams, a "rows so far" progress line at most this often (seconds)
PROGRESS_EVERY_S = 15


def load_iris(conn, cohort: str, sources: dict | None = None, cohort_params: dict | None = None,
              snapshot_dir: Path | None = None, progress=None) -> tuple[Dataset, dict]:
    """IRIS path: reads one cohort from a DB-API connection (io/iris.connect). Returns the same as `load`;
    each source in the report also carries the `query` that ran and the result's `sha256` (audit input).

    snapshot_dir: each source's result is written as CSV under its `file` name — `load(snapshot_dir, cohort)`
    gives the same Dataset. When the mapping dictionaries change, ingest can be redone without going back to IRIS.
    progress(message): where the read is (query sent, rows so far, rows read, mapping) — screen output only.
    """
    say = progress or (lambda msg: None)
    params = {"cohort": cohort, **(IRIS_COHORTS.get(cohort, {}) if cohort_params is None else cohort_params)}
    snap = Path(snapshot_dir) if snapshot_dir else None
    if snap:
        snap.mkdir(parents=True, exist_ok=True)

    def read(name: str, spec: dict):
        t0 = last = time.monotonic()

        def rows_so_far(n: int) -> None:
            nonlocal last
            now = time.monotonic()
            if now - last >= PROGRESS_EVERY_S:
                last = now
                say(f"{name}: {n:,} rows so far ({now - t0:.0f} s)")

        say(f"{name}: querying {spec.get('table', 'custom query').rsplit('.', 1)[-1]}")
        try:
            sql = iris_query(conn, spec, name, params)
            df, text = iris.fetch(conn, sql, progress=rows_so_far)
        except (KeyError, ValueError):
            raise                                   # mapping / query error: never silent, even for an optional source
        except Exception as e:                      # driver error (e.g. no such table)
            if not spec.get("optional"):
                raise
            if snap and (snap / spec["file"]).exists():
                (snap / spec["file"]).unlink()      # don't mix in a file left over from an earlier snapshot
            say(f"{name}: absent (optional source)")
            return None, {"status": "absent (optional)", "error": f"{type(e).__name__}: {str(e)[:300]}"}
        say(f"{name}: {len(df):,} rows read ({time.monotonic() - t0:.0f} s)")
        info = {"query": sql, "sha256": iris.sha256_text(text)}
        if snap:
            p = snap / spec["file"]
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
            info["snapshot"] = str(p)
        return df, info

    return _load(cohort, sources or SOURCES, read, "iris", progress)


def _load(cohort: str, sources: dict, read, input_kind: str, progress=None) -> tuple[Dataset, dict]:
    say = progress or (lambda msg: None)
    parts: dict[str, list[pd.DataFrame]] = {t: [] for t in TABLES}
    report: dict = {"cohort": cohort, "input": input_kind, "sources": {}, "value_counts": []}
    for name, spec in sources.items():
        raw, got = read(name, spec)
        if raw is None:
            report["sources"][name] = got
            continue
        t0 = time.monotonic()
        df, info = _select(raw, spec, name, got.get("file") or "IRIS query")
        df = _parse_dates(df, spec, info)
        extra = {"item_filtered": bool(spec.get("filter"))} if spec["kind"] == "smoking" else {}
        produced = HANDLERS[spec["kind"]](df, name, report["value_counts"], **extra)
        info.update(got)
        info.update(status="read", rows_out={t: int(len(d)) for t, d in produced.items()})
        report["sources"][name] = info
        for t, d in produced.items():
            parts[t].append(d)
        say(f"{name}: mapped → {sum(info['rows_out'].values()):,} canonical rows ({time.monotonic() - t0:.0f} s)")

    tables = {}
    for t in TABLES:
        frames = [f for f in parts[t] if len(f)]
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=list(SCHEMA[t]))
        tables[t] = coerce(df, t)
    return Dataset(source="nabidh", cohort=cohort, tables=tables), report
