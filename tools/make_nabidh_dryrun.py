"""Dry-run data: synthetic canonical C1 / C2 / C3 → the shape of the HSAA views in the enclave (adapter SOURCES).

Purpose: run the tools/ingest_nabidh.py → NB0 → NB1 (→ NB2) chain end to end through the NABIDH adapter.
Follows the views seen in the enclave (2026-11-18):
- Patient: ID, Age (no date of birth; age as of AGE_REFERENCE_DATE), Gender_Code (M/F),
  EthnicGroup_Description; no nationality. In the other views the patient key is `Patient` (= Patient.ID)
- Diagnosis (ICD-10 only, incl. Z83.3), Observation (BMI, height, weight — LOINC; no unit column; as in C1,
  some rows have an empty ObservationValue or the placeholder "0" — the adapter drops them — and a few heights
  are in metres),
  LabResultItem (HbA1c, FPG, OGTT — LOINC, with units; C1 DDL 2026-11-19; as on the VM, units in several spellings
  (mg/dL, MG/DL, mg/dl), "0" / "NULL" as HbA1c unit and some empty ResultValue rows), SocialHistory (smoking),
  FamilyHistory (diabetes), Medication; Encounter only in C3
- C3 differences: SocialHabitCategory_Description (not _Code; C1 and C2 have _Code, VM checks 2026-11-20)
- Medication: in C1 / C2 DrugProduct_Code = DDC product code (the real C2 has drug codes, VM ingest 2026-11-19); in
  C3 no DrugProduct_Code, DrugProduct_Description = DDC trade name (a single-ingredient, systemic DDC product
  matching the synthetic drug name; this exercises the io/adapters/ddc.py name mapping)
- not delivered: waist circumference, other vitals, random glucose
SYNTHETIC — not real patient data. The first line of each file says so.

Usage:
  python tools/build_synthetic_cohorts.py        # first (data/canonical/synthetic)
  python tools/make_nabidh_dryrun.py             # → data/nabidh_dryrun/raw/<c1|c2|c3>/ (CSV)
                                                 #   + data/nabidh_dryrun/iris/<c1|c2|c3>.sqlite (instead of IRIS)
  python tools/ingest_nabidh.py --raw-root data/nabidh_dryrun/raw --source nabidh_dryrun
  SANDBOX_SOURCE=nabidh_dryrun python notebooks/00_data_profile.py   (same for NB1, NB2)

Dry run of the IRIS path (the adapter's `table` names, IRIS_COHORTS schemas; SQLite instead of the driver):
  python tools/ingest_nabidh.py --input iris --iris-sqlite data/nabidh_dryrun/iris --source nabidh_dryrun_iris
  → canonical output must match the file path's (data/canonical/nabidh_dryrun vs nabidh_dryrun_iris)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from sandbox import codelists  # noqa: E402
from sandbox.audit import Run  # noqa: E402
from sandbox.config import CANONICAL_DIR, COHORTS, DATA_DIR  # noqa: E402
from sandbox.io import iris, schema  # noqa: E402
from sandbox.io.adapters import ddc, nabidh  # noqa: E402

OUT_ROOT = DATA_DIR / "nabidh_dryrun" / "raw"
IRIS_ROOT = DATA_DIR / "nabidh_dryrun" / "iris"
BANNER = "# SYNTHETIC DRY RUN — NOT REAL PATIENT DATA\n"
DELIVERED_LABS = ["4548-4", "1558-6", "1521-4"]
VITAL_LOINC = {"bmi": "39156-5", "height_cm": "8302-2", "weight_kg": "3141-9"}


def _write(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(BANNER)
        df.to_csv(fh, index=False)
    return path


def _d(s: pd.Series) -> pd.Series:
    return s.dt.strftime("%Y-%m-%d")


def _age(dob: pd.Series, ref: pd.Timestamp) -> pd.Series:
    """Age in whole years on the reference day."""
    before = (dob.dt.month > ref.month) | ((dob.dt.month == ref.month) & (dob.dt.day > ref.day))
    return (ref.year - dob.dt.year - before.astype(int)).astype("Int64")


def ddc_products(drug_names: pd.Series) -> pd.DataFrame:
    """Synthetic drug name ("Insulin glargine") → a single-ingredient, systemic DDC product containing the same
    active ingredient (code + trade name). If none is found, that name keeps its ATC as the code."""
    ref = ddc.load_reference()
    cand = ref[(ref["atc_codes"].str.len() == 1) & ~ref["ingredients"].str.contains("/", na=False)]
    cand = cand.sort_values(["status", "ddc_code"])            # Active first, then by code (deterministic)
    rows = []
    for name in sorted(drug_names.dropna().unique()):
        words = name.upper().split()
        m = cand[cand["ingredients"].map(lambda i: all(w in i.split() or w in i for w in words))]
        if len(m):
            rows.append({"drug_name": name, "ddc_code": m["ddc_code"].iloc[0], "trade_name": m["trade_name"].iloc[0]})
    return pd.DataFrame(rows, columns=["drug_name", "ddc_code", "trade_name"])


def convert(ds: schema.Dataset, cohort: str) -> dict[str, pd.DataFrame]:
    pts, cond, labs, obs, meds = (ds[t] for t in ("patients", "conditions", "labs", "observations", "medications"))
    out = {}
    out["patients.csv"] = pd.DataFrame({
        "ID": pts["patient_id"], "Age": _age(pts["date_of_birth"], pd.Timestamp(nabidh.AGE_REFERENCE_DATE)),
        "EthnicGroup_Description": pts["ethnicity_raw"], "Gender_Code": pts["sex"].map({"Male": "M", "Female": "F"})})
    icd = cond[cond["code_system"] == "ICD-10"]
    out["diagnoses.csv"] = pd.DataFrame({
        "ID": range(1, len(icd) + 1), "DiagnosisDate": _d(icd["date"]), "Patient": icd["patient_id"],
        "Diagnosis_Code": icd["code"], "Diagnosis_Description": icd["description"]})

    vit = obs[obs["concept"].isin(list(VITAL_LOINC))]
    vit = vit.reset_index(drop=True)
    # As in the VM checks (2026-11-20): a few heights in metres (the adapter converts them back to cm)
    metres = vit["concept"].eq("height_cm") & (vit.index % 50 == 7)
    vit.loc[metres, "value"] = (pd.to_numeric(vit.loc[metres, "value"]) / 100).round(3).astype(str)
    vit = pd.concat([vit, vit.iloc[::25].assign(value=pd.NA),                         # empty-value rows (as in C1)
                     vit.iloc[3::30].assign(value="0")], ignore_index=True)           # "0" placeholder rows
    out["observations.csv"] = pd.DataFrame({
        "ID": range(1, len(vit) + 1), "Patient": vit["patient_id"],
        "ObservationCode_Code": vit["concept"].map(VITAL_LOINC), "ObservationCode_Description": vit["concept"],
        "ObservationValue": vit["value"], "ObservationDate": _d(vit["date"])})
    lab = labs[labs["loinc"].isin(DELIVERED_LABS)].reset_index(drop=True)
    # As in the VM ingest 1.2.1 (2026-11-19): one unit in several spellings, "0" / "NULL" as HbA1c unit, empty values
    unit = lab["unit"].astype("string")
    unit = unit.where(lab.index % 5 != 1, unit.str.upper()).where(lab.index % 11 != 2, unit.str.lower())
    a1c = lab["loinc"].eq("4548-4")
    unit = unit.where(~(a1c & (lab.index % 40 == 3)), "0").where(~(a1c & (lab.index % 40 == 23)), "NULL")
    lab = pd.concat([lab.assign(unit=unit), lab.iloc[::60].assign(value=pd.NA)], ignore_index=True)
    out["lab_results.csv"] = pd.DataFrame({
        "ID": range(1, len(lab) + 1), "Encounter": pd.NA, "Patient": lab["patient_id"], "ResultDate": _d(lab["date"]),
        "ResultValue": lab["value"], "ResultValueUnits": lab["unit"], "TestItemCode_Code": lab["loinc"],
        "TestItemCode_Description": lab["test_name"]})

    sm = obs[obs["concept"] == "smoking_status"]
    item = "SocialHabitCategory_Description" if cohort == "c3" else "SocialHabitCategory_Code"
    out["social_history.csv"] = pd.DataFrame({
        "ID": range(1, len(sm) + 1), "EnteredOn": _d(sm["date"]), "Patient": sm["patient_id"],
        item: "Tobacco", "SocialHabitQty_Description": sm["value"]})

    fh = cond[codelists.match_dx(cond, "family_history_dm")]
    out["family_history.csv"] = pd.DataFrame({
        "ID": range(1, len(fh) + 1), "EnteredOn": _d(fh["date"]), "Patient": fh["patient_id"],
        "Diagnosis_Code": fh["code"], "Diagnosis_Description": "Diabetes mellitus", "FamilyMember_Description": pd.NA})

    prod = ddc_products(meds["drug_name"]).set_index("drug_name")
    code = meds["drug_name"].map(prod["ddc_code"]).fillna(meds["atc_code"])
    med = pd.DataFrame({
        "ID": range(1, len(meds) + 1), "FromTime": _d(meds["date"]), "Patient": meds["patient_id"],
        "ToTime": pd.NA, "DrugProduct_Code": code, "DrugProduct_Description": meds["drug_name"],
        "Route_Description": meds["route"]})
    if cohort == "c3":                                         # no code; name = DDC trade name
        med["DrugProduct_Description"] = meds["drug_name"].map(prod["trade_name"]).fillna(meds["drug_name"])
        med = med.drop(columns=["DrugProduct_Code"])
    out["medications.csv"] = med

    if cohort == "c3":
        enc = ds["encounters"]
        out["encounters.csv"] = pd.DataFrame({
            "ID": enc["encounter_id"], "EncounterEndDate": _d(enc["date"]), "EncounterStartDate": _d(enc["date"]),
            "EncounterType": enc["encounter_type"], "Patient": enc["patient_id"]})
    return out


def main() -> None:
    run = Run("make_nabidh_dryrun", source="nabidh_dryrun")
    for c in COHORTS:
        src = CANONICAL_DIR / "synthetic" / c
        if not src.exists():
            continue
        run.add_inputs([src])
        files = convert(schema.read_dataset(CANONICAL_DIR, "synthetic", c), c)
        for old in (OUT_ROOT / c).glob("*.csv"):          # don't mix in files from an earlier dry run
            old.unlink()
        for fname, df in files.items():
            run.register_output(_write(df, OUT_ROOT / c / fname), f"dry run {c} {fname}")
        # The same tables under their IRIS names (SOURCES[...]["table"], without the schema prefix) in one SQLite file
        table_of = {spec["file"]: spec["table"].split(".", 1)[-1] for spec in nabidh.SOURCES.values()}
        db = iris.write_sqlite_standin(IRIS_ROOT / f"{c}.sqlite", {table_of[f]: df for f, df in files.items()})
        run.register_output(db, f"dry run {c} IRIS stand-in (SQLite)")
        run.log(f"{c} written", files={k: len(v) for k, v in files.items()})
        print(c, {k: len(v) for k, v in files.items()})
    run.finish()
    print("run:", run.run_id, "→", OUT_ROOT, "and", IRIS_ROOT)


if __name__ == "__main__":
    main()
