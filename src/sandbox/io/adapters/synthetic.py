"""Synthetic NABIDH-like raw CSVs → canonical schema.

Raw files (data/synthetic/raw/): patients, encounters, conditions,
medications, observations, labs. The first line may carry a "# SYNTHETIC ..." banner.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from ... import codelists
from ..schema import Dataset, coerce


# Synthetic data has no nationality. To exercise the pipeline with PARAMS["ethnicity_source"] = "nationality",
# a representative nationality is derived from the synthetic ethnicity (test only; codelists maps it back to the
# same group).
SYNTHETIC_ETHNICITY_TO_NATIONALITY = {
    "Emirati": "United Arab Emirates", "Gulf Arab (non-Emirati)": "Saudi Arabia", "Arab (non-Gulf)": "Egypt",
    "Indian": "India", "Pakistani": "Pakistan", "Bangladeshi": "Bangladesh", "Filipino": "Philippines",
    "Other Asian": "Nepal", "African": "Kenya", "Western": "United Kingdom",
}


def read_raw_csv(path: Path, sep: str = ",", encoding: str = "utf-8-sig") -> pd.DataFrame:
    """Reads a CSV, skipping leading banner line(s) starting with '#'; everything as text.
    utf-8-sig: strips the BOM from files exported by Excel (plain UTF-8 reads too)."""
    skip = 0
    with open(path, encoding=encoding) as fh:
        for line in fh:
            if line.startswith("#"):
                skip += 1
            else:
                break
    return pd.read_csv(path, skiprows=skip, dtype=str, keep_default_na=False,
                       na_values=[""], encoding=encoding, sep=sep)


def read_raw_csv_text(text: str, sep: str = ",") -> pd.DataFrame:
    """Same rules as read_raw_csv, for CSV text in memory (IRIS query result, io/iris.py)."""
    return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, na_values=[""], sep=sep)


def load(raw_dir: Path) -> Dataset:
    raw_dir = Path(raw_dir)
    r = {n: read_raw_csv(raw_dir / f"{n}.csv") for n in
         ["patients", "encounters", "conditions", "medications", "observations", "labs"]}

    enc = r["encounters"].rename(columns={"encounter_date": "date"})

    # Most frequent facility per patient (for the facility representation report)
    if len(enc):
        main_fac = (enc.dropna(subset=["facility_id"])
                    .groupby(["patient_id", "facility_id"]).size()
                    .reset_index(name="n").sort_values(["patient_id", "n"], ascending=[True, False])
                    .drop_duplicates("patient_id").set_index("patient_id")["facility_id"])
    else:
        main_fac = pd.Series(dtype="string")

    pts = r["patients"].rename(columns={"ethnicity_nabidh": "ethnicity_raw"})
    pts["facility_id"] = pts["patient_id"].map(main_fac)
    if "nationality" not in pts.columns:
        pts["nationality"] = pts["ethnicity_raw"].map(SYNTHETIC_ETHNICITY_TO_NATIONALITY)

    cond = r["conditions"].rename(columns={"recorded_date": "date", "code_description": "description"})
    meds = r["medications"].rename(columns={"prescription_date": "date"})
    labs = r["labs"]

    obs = r["observations"].copy()
    obs["concept"] = obs["concept"].str.strip().str.lower().map(codelists.OBS_NAME_TO_CONCEPT).fillna(
        obs["concept"].str.strip().str.lower())

    tables = {
        "patients": coerce(pts, "patients"),
        "conditions": coerce(cond, "conditions"),
        "medications": coerce(meds, "medications"),
        "labs": coerce(labs, "labs"),
        "observations": coerce(obs, "observations"),
        "encounters": coerce(enc, "encounters"),
    }
    return Dataset(source="synthetic", cohort="full", tables=tables)
