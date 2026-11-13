"""Klinik kod listeleri (MVP Dataset v1.0, Interim Data Assessment, Cohort Spec v2).

Kurallar:
- ICD-10 kodları prefix ile eşleşir ("E11" → E11, E11.9, E1165 ...). Noktalar
  karşılaştırmada yok sayılır.
- SNOMED / LOINC / ATC tam kod veya prefix (ATC) ile eşleşir.
- Her liste "requested" olarak NB0'daki istenen-vs-gelen eşlemesinde kullanılır.
"""
from __future__ import annotations

import pandas as pd

# --------------------------------------------------------------------------
# Tanılar (ICD-10 prefix) + SNOMED karşılıkları
# --------------------------------------------------------------------------
DX = {
    "t2d": {"icd10": ["E11"], "snomed": ["44054006"]},
    "t1d": {"icd10": ["E10"], "snomed": ["46635009"]},
    "prediabetes": {"icd10": ["R73"], "snomed": ["714628002", "9414007", "390951007"]},
    "hypertension": {"icd10": ["I10", "I11", "I12", "I13", "I15", "I16", "I1A"], "snomed": ["38341003"]},
    "cvd": {
        "icd10": ["I20", "I21", "I22", "I23", "I24", "I25", "I50",
                  "I60", "I61", "I62", "I63", "I64", "I65", "I66", "I67", "I68", "I69", "G45"],
        "snomed": ["414545008", "84114007", "230690007"],
    },
    "family_history_dm": {"icd10": ["Z833"], "snomed": ["160303001"]},
    "obesity": {"icd10": ["E66"], "snomed": ["414915002"]},
    "bmi_code": {"icd10": ["Z68"], "snomed": []},
    "smoking_current": {"icd10": ["Z720", "F17200", "F17210", "F17220", "F17290"], "snomed": ["77176002", "449868002", "428041000124106"]},
    "smoking_ex": {"icd10": ["Z87891", "F17201", "F17211", "F17221", "F17291"], "snomed": ["8517006"]},
    "smoking_never": {"icd10": [], "snomed": ["266919005"]},
    # QDiabetes Model A ek prediktörleri (revize MVP'de kapsam dışı; varsa kullanılır)
    "gdm": {"icd10": ["O244", "Z8632"], "snomed": []},
    "pcos": {"icd10": ["E282"], "snomed": []},
    "learning_disability": {"icd10": ["F70", "F71", "F72", "F73", "F78", "F79"], "snomed": []},
    "schizophrenia_bipolar": {"icd10": ["F20", "F25", "F31"], "snomed": []},
}

# --------------------------------------------------------------------------
# İlaçlar (ATC prefix)
# --------------------------------------------------------------------------
ATC = {
    "antidiabetic": ["A10"],
    "antihypertensive": ["C02", "C03", "C07", "C08", "C09"],
    "statin": ["C10AA"],
    "corticosteroid": ["H02AB"],
    "atypical_antipsychotic": ["N05AH", "N05AX", "N05AL"],
}

# --------------------------------------------------------------------------
# Lablar (LOINC)
# --------------------------------------------------------------------------
LOINC_LAB = {
    "4548-4": "hba1c",          # %
    "17856-6": "hba1c",         # HbA1c (HPLC) %
    "59261-8": "hba1c_ifcc",    # mmol/mol → % dönüştürülür
    "1558-6": "fpg",            # mg/dL
    "1521-4": "ogtt_2h",        # mg/dL
    "2345-7": "random_glucose", # mg/dL
    "2339-0": "random_glucose", # Glucose [Mass/volume] in Blood
}

# --------------------------------------------------------------------------
# Gözlemler: kaynak kod → kanonik concept
# --------------------------------------------------------------------------
OBS_CODE_TO_CONCEPT = {
    ("LOINC", "39156-5"): "bmi",
    ("LOINC", "8302-2"): "height_cm",
    ("LOINC", "3141-9"): "weight_kg",
    ("LOINC", "29463-7"): "weight_kg",
    ("LOINC", "8280-0"): "waist_cm",
    ("LOINC", "56086-2"): "waist_cm",
    ("LOINC", "62409-8"): "hip_cm",
    ("LOINC", "8480-6"): "sbp",
    ("LOINC", "8462-4"): "dbp",
    ("LOINC", "72166-2"): "smoking_status",
    ("LOINC", "11331-6"): "alcohol_use",
    ("SNOMED", "60621009"): "bmi",
    ("SNOMED", "276361009"): "waist_cm",
    ("SNOMED", "248361005"): "hip_cm",
    ("SNOMED", "401201003"): "pack_years",
}

# Kaynakta serbest metin concept adı geldiğinde (ör. sentetik veri)
OBS_NAME_TO_CONCEPT = {
    "bmi": "bmi", "height_cm": "height_cm", "weight_kg": "weight_kg",
    "waist_cm": "waist_cm", "hip_cm": "hip_cm", "systolic_bp": "sbp",
    "diastolic_bp": "dbp", "smoking_status": "smoking_status",
    "alcohol_use": "alcohol_use", "pack_years": "pack_years",
    "self_rated_health": "self_rated_health",
}

# Sigara durumu serbest metin → QDiabetes kategorisi
# 0 non, 1 ex, 2 light, 3 moderate, 4 heavy. "current" yoğunluksuz → None (karar: config)
SMOKING_TEXT_TO_CAT = {
    "never": 0, "non": 0, "non-smoker": 0, "nonsmoker": 0,
    "ex": 1, "former": 1, "ex-smoker": 1,
    "light": 2, "moderate": 3, "heavy": 4,
    "current": None,
}

# --------------------------------------------------------------------------
# 8 çekirdek değişken (revize MVP) + LRS ek değişkeni
# --------------------------------------------------------------------------
CORE_VARIABLES = [
    "sex", "age", "ethnicity", "bmi", "smoking", "family_history", "cvd", "hypertension",
]
SUPPLEMENTAL_VARIABLES = ["waist"]


# --------------------------------------------------------------------------
# Eşleştirme yardımcıları
# --------------------------------------------------------------------------
def norm_icd(code: pd.Series) -> pd.Series:
    """ICD-10 kodunu karşılaştırma için normalize et: büyük harf, nokta/boşluk yok."""
    return code.astype("string").str.upper().str.replace(r"[.\s]", "", regex=True)


def match_dx(conditions: pd.DataFrame, group: str) -> pd.Series:
    """conditions satırlarının verilen tanı grubuna uyup uymadığını döndürür (bool Series)."""
    spec = DX[group]
    system = conditions["code_system"].astype("string").str.upper()
    code_norm = norm_icd(conditions["code"])
    is_icd = system.str.startswith("ICD")
    icd_hit = pd.Series(False, index=conditions.index)
    if spec["icd10"]:
        icd_hit = code_norm.str.startswith(tuple(spec["icd10"])).fillna(False)
    sn_hit = pd.Series(False, index=conditions.index)
    if spec["snomed"]:
        sn_hit = conditions["code"].astype("string").isin(spec["snomed"]).fillna(False)
    return ((is_icd & icd_hit) | (system.str.startswith("SNOMED") & sn_hit)).fillna(False).astype(bool)


def match_atc(medications: pd.DataFrame, group: str) -> pd.Series:
    code = medications["atc_code"].astype("string").str.upper().str.replace(" ", "", regex=False)
    return code.str.startswith(tuple(ATC[group])).fillna(False).astype(bool)


def requested_codes_table() -> pd.DataFrame:
    """NB0 'istenen vs gelen' eşlemesi için düz liste."""
    rows = []
    for group, spec in DX.items():
        for c in spec["icd10"]:
            rows.append(("condition", group, "ICD-10", c))
        for c in spec["snomed"]:
            rows.append(("condition", group, "SNOMED", c))
    for group, codes in ATC.items():
        for c in codes:
            rows.append(("medication", group, "ATC", c))
    for code, name in LOINC_LAB.items():
        rows.append(("lab", name, "LOINC", code))
    for (system, code), name in OBS_CODE_TO_CONCEPT.items():
        rows.append(("observation", name, system, code))
    return pd.DataFrame(rows, columns=["table", "group", "code_system", "code"])
