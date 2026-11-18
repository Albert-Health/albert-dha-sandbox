"""Prova verisi: sentetik kanonik C1 / C2 / C3 → enclave'deki HSAA view'larının biçimi (adapter SOURCES).

Amaç: tools/ingest_nabidh.py → NB0 → NB1 (→ NB2) zincirini NABIDH adapter'ı üzerinden uçtan uca
çalıştırmak. Enclave'de görülen view'lara uyulur (2026-11-18):
- Patient: ID, Age (doğum tarihi yok; yaş AGE_REFERENCE_DATE'e göre), Gender_Code (M/F),
  EthnicGroup_Description; uyruk yok. Diğer view'larda hasta anahtarı `Patient` (= Patient.ID)
- Diagnosis (yalnız ICD-10, Z83.3 dahil), Observation (HbA1c, FPG, OGTT, BMI, boy, kilo — LOINC; birim
  sütunu yok), SocialHistory (sigara), FamilyHistory (diyabet), Medication; Encounter yalnız C3
- C2 farkları: SocialHabitCategory_Description (_Code değil), Medication'da DrugProduct_Code yok
- verilmeyenler: bel çevresi, diğer vital'ler, random glukoz
SENTETİK — gerçek hasta verisi değildir. Dosyaların ilk satırı bunu belirtir.

Kullanım:
  python tools/build_synthetic_cohorts.py        # önce (data/canonical/synthetic)
  python tools/make_nabidh_dryrun.py             # → data/nabidh_dryrun/raw/<c1|c2|c3>/ (CSV)
                                                 #   + data/nabidh_dryrun/iris/<c1|c2|c3>.sqlite (IRIS yerine)
  python tools/ingest_nabidh.py --raw-root data/nabidh_dryrun/raw --source nabidh_dryrun
  SANDBOX_SOURCE=nabidh_dryrun python notebooks/00_data_profile.py   (NB1, NB2 aynı)

IRIS yolunun provası (adapter'daki `table` adları, IRIS_COHORTS şemaları; sürücü yerine SQLite):
  python tools/ingest_nabidh.py --input iris --iris-sqlite data/nabidh_dryrun/iris --source nabidh_dryrun_iris
  → kanonik çıktı, dosya yolundakiyle aynı olmalı (data/canonical/nabidh_dryrun vs nabidh_dryrun_iris)
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
from sandbox.io.adapters import nabidh  # noqa: E402

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
    """Referans günündeki tam yıl yaş."""
    before = (dob.dt.month > ref.month) | ((dob.dt.month == ref.month) & (dob.dt.day > ref.day))
    return (ref.year - dob.dt.year - before.astype(int)).astype("Int64")


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

    lab = labs[labs["loinc"].isin(DELIVERED_LABS)]
    vit = obs[obs["concept"].isin(list(VITAL_LOINC))]
    m = pd.concat([
        pd.DataFrame({"Patient": lab["patient_id"], "ObservationCode_Code": lab["loinc"],
                      "ObservationCode_Description": lab["test_name"], "ObservationValue": lab["value"],
                      "ObservationDate": _d(lab["date"])}),
        pd.DataFrame({"Patient": vit["patient_id"], "ObservationCode_Code": vit["concept"].map(VITAL_LOINC),
                      "ObservationCode_Description": vit["concept"], "ObservationValue": vit["value"],
                      "ObservationDate": _d(vit["date"])}),
    ], ignore_index=True)
    out["observations.csv"] = m.assign(ID=range(1, len(m) + 1))

    sm = obs[obs["concept"] == "smoking_status"]
    item = "SocialHabitCategory_Description" if cohort == "c2" else "SocialHabitCategory_Code"
    out["social_history.csv"] = pd.DataFrame({
        "ID": range(1, len(sm) + 1), "EnteredOn": _d(sm["date"]), "Patient": sm["patient_id"],
        item: "Tobacco", "SocialHabitQty_Description": sm["value"]})

    fh = cond[codelists.match_dx(cond, "family_history_dm")]
    out["family_history.csv"] = pd.DataFrame({
        "ID": range(1, len(fh) + 1), "EnteredOn": _d(fh["date"]), "Patient": fh["patient_id"],
        "Diagnosis_Code": fh["code"], "Diagnosis_Description": "Diabetes mellitus", "FamilyMember_Description": pd.NA})

    med = pd.DataFrame({
        "ID": range(1, len(meds) + 1), "FromTime": _d(meds["date"]), "Patient": meds["patient_id"],
        "ToTime": pd.NA, "DrugProduct_Code": meds["atc_code"], "DrugProduct_Description": meds["drug_name"],
        "Route_Description": meds["route"]})
    out["medications.csv"] = med.drop(columns=["DrugProduct_Code"]) if cohort == "c2" else med

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
        for old in (OUT_ROOT / c).glob("*.csv"):          # önceki provadan kalan dosya karışmasın
            old.unlink()
        for fname, df in files.items():
            run.register_output(_write(df, OUT_ROOT / c / fname), f"dry run {c} {fname}")
        # Aynı tablolar, IRIS'teki adlarıyla (SOURCES[...]["table"], şema öneki olmadan) tek SQLite dosyasında
        table_of = {spec["file"]: spec["table"].split(".", 1)[-1] for spec in nabidh.SOURCES.values()}
        db = iris.write_sqlite_standin(IRIS_ROOT / f"{c}.sqlite", {table_of[f]: df for f, df in files.items()})
        run.register_output(db, f"dry run {c} IRIS stand-in (SQLite)")
        run.log(f"{c} written", files={k: len(v) for k, v in files.items()})
        print(c, {k: len(v) for k, v in files.items()})
    run.finish()
    print("run:", run.run_id, "→", OUT_ROOT, "ve", IRIS_ROOT)


if __name__ == "__main__":
    main()
