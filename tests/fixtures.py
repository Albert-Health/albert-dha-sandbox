"""El yapımı küçük test veri seti — kohort kurallarının beklenen sonuçları bilinir."""
from __future__ import annotations

import pandas as pd

from sandbox.io.schema import Dataset, coerce


def _df(rows, cols):
    return pd.DataFrame(rows, columns=cols)


def tiny_dataset() -> Dataset:
    """
    P01 C3 uygun: 2019 normal HbA1c, 2021 HbA1c 6.8 → incident (lab_hba1c)
    P02 C3 uygun: 2019 normal FPG, 2022 normal HbA1c → non-event, sansür 2022
    P03 C3 dışı: index sonrası ölçüm yok
    P04 C3 dışı: 2018 R73 (prediyabet) normalden önce → prevalent
    P05 C3 dışı: E10 (T1D) → her yerden hariç
    P06 C3 dışı: index'te 22 yaş
    P07 C3 uygun ama ilaç-tek outcome: 2023 A10 → birincilde event yok, duyarlılıkta var
    P08 pozitif havuz (T2DM, tanı), 8 değişken tam → C1 adayı
    P09 pozitif havuz (prediyabet lab), sigara yok → C1 dışı, C2 adayı
    P10 C3: 2018 A10, 2019 normal HbA1c → prevalent (ilaç) → hariç
    """
    pts = _df([
        ("P01", "Male", "1970-01-01", "Emirati", None, "F1"),
        ("P02", "Female", "1965-06-15", "Indian", None, "F1"),
        ("P03", "Male", "1960-01-01", "Pakistani", None, "F2"),
        ("P04", "Female", "1975-01-01", "Filipino", None, "F2"),
        ("P05", "Male", "1980-01-01", "Emirati", None, "F1"),
        ("P06", "Female", "1997-01-01", "Western", None, "F3"),
        ("P07", "Male", "1955-01-01", "Not recorded", None, "F3"),
        ("P08", "Male", "1960-01-01", "Emirati", None, "F1"),
        ("P09", "Female", "1985-01-01", "Indian", None, "F1"),
        ("P10", "Male", "1950-01-01", "Indian", None, "F2"),
    ], ["patient_id", "sex", "date_of_birth", "ethnicity_raw", "nationality", "facility_id"])

    labs = _df([
        ("P01", "4548-4", "HbA1c", 5.4, "%", "2019-03-01"),
        ("P01", "4548-4", "HbA1c", 6.8, "%", "2021-05-01"),
        ("P02", "1558-6", "FPG", 92, "mg/dL", "2019-04-01"),
        ("P02", "4548-4", "HbA1c", 5.5, "%", "2022-02-01"),
        ("P03", "4548-4", "HbA1c", 5.2, "%", "2020-01-01"),
        ("P04", "4548-4", "HbA1c", 5.3, "%", "2019-01-01"),
        ("P04", "4548-4", "HbA1c", 5.4, "%", "2020-01-01"),
        ("P05", "4548-4", "HbA1c", 5.3, "%", "2019-01-01"),
        ("P05", "4548-4", "HbA1c", 5.3, "%", "2020-01-01"),
        ("P06", "4548-4", "HbA1c", 5.1, "%", "2019-01-01"),
        ("P06", "4548-4", "HbA1c", 5.2, "%", "2020-01-01"),
        ("P07", "4548-4", "HbA1c", 5.6, "%", "2019-01-01"),
        ("P07", "4548-4", "HbA1c", 5.6, "%", "2024-01-01"),
        ("P09", "4548-4", "HbA1c", 6.0, "%", "2021-01-01"),
        ("P10", "4548-4", "HbA1c", 5.5, "%", "2019-01-01"),
        ("P10", "4548-4", "HbA1c", 5.6, "%", "2020-01-01"),
    ], ["patient_id", "loinc", "test_name", "value", "unit", "date"])

    cond = _df([
        ("P04", "ICD-10", "R73.03", "Prediabetes", "2018-06-01"),
        ("P05", "ICD-10", "E10.9", "T1D", "2021-01-01"),
        ("P08", "ICD-10", "E11.9", "T2D", "2020-01-01"),
        ("P08", "ICD-10", "I10", "HTN", "2019-01-01"),
        ("P02", "ICD-10", "Z83.3", "FH DM", "2018-01-01"),
    ], ["patient_id", "code_system", "code", "description", "date"])

    meds = _df([
        ("P07", "A10BA02", "Metformin", "2023-01-01", "Oral"),
        ("P08", "C09AA02", "Enalapril", "2019-02-01", "Oral"),
        ("P10", "A10BA02", "Metformin", "2018-06-01", "Oral"),
    ], ["patient_id", "atc_code", "drug_name", "date", "route"])

    obs = _df([
        ("P01", "bmi", "LOINC", "39156-5", "29.1", "kg/m2", "2019-02-01"),
        ("P02", "height_cm", "LOINC", "8302-2", "160", "cm", "2015-01-01"),
        ("P02", "weight_kg", "LOINC", "3141-9", "64", "kg", "2019-01-01"),
        ("P08", "bmi", "LOINC", "39156-5", "31.0", "kg/m2", "2020-01-01"),
        ("P08", "smoking_status", None, None, "ex", None, "2020-01-01"),
        ("P09", "bmi", "LOINC", "39156-5", "24.0", "kg/m2", "2021-01-01"),
        ("P01", "smoking_status", None, None, "never", None, "2019-02-01"),
    ], ["patient_id", "concept", "code_system", "code", "value", "unit", "date"])

    tables = {
        "patients": coerce(pts, "patients"),
        "labs": coerce(labs, "labs"),
        "conditions": coerce(cond, "conditions"),
        "medications": coerce(meds, "medications"),
        "observations": coerce(obs, "observations"),
        "encounters": coerce(pd.DataFrame(), "encounters"),
    }
    return Dataset(source="test", cohort="full", tables=tables)
