"""Prova verisi: sentetik kanonik C1 / C2 / C3 → NABIDH teslim biçimi (adapter SOURCES'taki örnek adlar).

Amaç: tools/ingest_nabidh.py → NB0 → NB1 (→ NB2) zincirini Pazartesiden önce NABIDH adapter'ı
üzerinden uçtan uca çalıştırmak. NABIDH "Data availability" listesine uyulur:
- verilenler: hasta profili (cinsiyet M/F, uyruk), tanılar (Z83.3 dahil), Observation (HbA1c, FPG,
  OGTT, BMI, boy, kilo — LOINC), SocialHistory (sigara), FamilyHistory (diyabet), Medication;
  Encounter yalnız C3
- verilmeyenler: bel çevresi, diğer vital'ler, random glukoz
SENTETİK — gerçek hasta verisi değildir. Dosyaların ilk satırı bunu belirtir.

Kullanım:
  python tools/build_synthetic_cohorts.py        # önce (data/canonical/synthetic)
  python tools/make_nabidh_dryrun.py             # → data/nabidh_dryrun/raw/<c1|c2|c3>/
  python tools/ingest_nabidh.py --raw-root data/nabidh_dryrun/raw --source nabidh_dryrun
  SANDBOX_SOURCE=nabidh_dryrun python notebooks/00_data_profile.py   (NB1, NB2 aynı)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from sandbox import codelists  # noqa: E402
from sandbox.audit import Run  # noqa: E402
from sandbox.config import CANONICAL_DIR, COHORTS, DATA_DIR  # noqa: E402
from sandbox.io import schema  # noqa: E402

OUT_ROOT = DATA_DIR / "nabidh_dryrun" / "raw"
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


def convert(ds: schema.Dataset, cohort: str) -> dict[str, pd.DataFrame]:
    pts, cond, labs, obs, meds = (ds[t] for t in ("patients", "conditions", "labs", "observations", "medications"))
    out = {}
    out["patients.csv"] = pd.DataFrame({
        "patient_id": pts["patient_id"], "sex": pts["sex"].map({"Male": "M", "Female": "F"}),
        "date_of_birth": _d(pts["date_of_birth"]), "nationality": pts["nationality"],
        "ethnicity": pts["ethnicity_raw"], "facility_id": pts["facility_id"]})
    out["diagnoses.csv"] = pd.DataFrame({
        "patient_id": cond["patient_id"], "code_system": cond["code_system"], "code": cond["code"],
        "description": cond["description"], "diagnosis_date": _d(cond["date"])})

    lab = labs[labs["loinc"].isin(DELIVERED_LABS)]
    vit = obs[obs["concept"].isin(list(VITAL_LOINC))]
    out["observations.csv"] = pd.concat([
        pd.DataFrame({"patient_id": lab["patient_id"], "code_system": "LN", "loinc": lab["loinc"],
                      "name": lab["test_name"], "value": lab["value"], "unit": lab["unit"], "date": _d(lab["date"])}),
        pd.DataFrame({"patient_id": vit["patient_id"], "code_system": "LN", "loinc": vit["concept"].map(VITAL_LOINC),
                      "name": vit["concept"], "value": vit["value"], "unit": vit["unit"], "date": _d(vit["date"])}),
    ], ignore_index=True)

    sm = obs[obs["concept"] == "smoking_status"]
    out["social_history.csv"] = pd.DataFrame({
        "patient_id": sm["patient_id"], "item": "Tobacco smoking status", "value": sm["value"],
        "code": sm["code"], "date": _d(sm["date"])})

    fh = cond[codelists.match_dx(cond, "family_history_dm")]
    out["family_history.csv"] = pd.DataFrame({
        "patient_id": fh["patient_id"], "relation": pd.NA, "condition": "Diabetes mellitus",
        "status": "Yes", "date": _d(fh["date"])})

    out["medications.csv"] = pd.DataFrame({
        "patient_id": meds["patient_id"], "atc_code": meds["atc_code"], "drug_name": meds["drug_name"],
        "prescription_date": _d(meds["date"]), "route": meds["route"]})

    if cohort == "c3":
        enc = ds["encounters"]
        out["encounters.csv"] = pd.DataFrame({
            "patient_id": enc["patient_id"], "encounter_id": enc["encounter_id"], "encounter_date": _d(enc["date"]),
            "facility_id": enc["facility_id"], "encounter_type": enc["encounter_type"]})
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
        run.log(f"{c} written", files={k: len(v) for k, v in files.items()})
        print(c, {k: len(v) for k, v in files.items()})
    run.finish()
    print("run:", run.run_id, "→", OUT_ROOT)


if __name__ == "__main__":
    main()
