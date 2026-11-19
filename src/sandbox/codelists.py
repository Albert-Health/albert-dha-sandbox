"""Clinical code lists (MVP Dataset v1.0, Interim Data Assessment, Cohort Spec v2).

Rules:
- ICD-10 codes match by prefix ("E11" → E11, E11.9, E1165 ...). Dots are
  ignored in the comparison.
- SNOMED / LOINC / ATC match by exact code or by prefix (ATC).
- Each list is used as "requested" in NB0's requested-vs-received mapping.
"""
from __future__ import annotations

import pandas as pd

# --------------------------------------------------------------------------
# Diagnoses (ICD-10 prefix) + SNOMED equivalents
# --------------------------------------------------------------------------
DX = {
    "t2d": {"icd10": ["E11"], "snomed": ["44054006"]},
    "t1d": {"icd10": ["E10"], "snomed": ["46635009"]},
    "prediabetes": {"icd10": ["R73"], "snomed": ["714628002", "9414007", "390951007"]},
    "hypertension": {"icd10": ["I10", "I11", "I12", "I13", "I15", "I16", "I1A"], "snomed": ["38341003"]},
    # [DECIDED: 2026-11-13, ensargunesdogdu] D18: the definition in the NABIDH Data availability list
    # (I20–I25, I50, I6x, G45) — same as this list.
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
    # Additional QDiabetes Model A predictors (out of scope in the revised MVP; used if present)
    "gdm": {"icd10": ["O244", "Z8632"], "snomed": []},
    "pcos": {"icd10": ["E282"], "snomed": []},
    "learning_disability": {"icd10": ["F70", "F71", "F72", "F73", "F78", "F79"], "snomed": []},
    "schizophrenia_bipolar": {"icd10": ["F20", "F25", "F31"], "snomed": []},
}

# --------------------------------------------------------------------------
# Medications (ATC prefix)
# --------------------------------------------------------------------------
ATC = {
    "antidiabetic": ["A10"],
    "antihypertensive": ["C02", "C03", "C07", "C08", "C09"],
    "statin": ["C10AA"],
    "corticosteroid": ["H02AB"],
    "atypical_antipsychotic": ["N05AH", "N05AX", "N05AL"],
}

# Active ingredient name → ATC (WHO ATC/DDD). When the source has no ATC code (Dubai Drug Code list, free-text drug
# name) the drug class is found here: io/adapters/ddc.py searches the ingredient name on word boundaries ("AMLODIPINE"
# → "AMLODIPINE (AS BESYLATE)" matches, "LEVAMLODIPINE" does not). Combination product → one row per active
# ingredient (e.g. AMLODIPINE/ATORVASTATIN → C08CA01 + C10AA05). Scope: active ingredients of the ATC groups above
# + N05AE (ziprasidone, lurasidone; atypical but not in ATC["atypical_antipsychotic"] — docs/gap.md D26).
# Codes are at level 5; those without a definite WHO code are one level up (A10A insulins, A10B, C08CA).
# All are systemic-use groups: eye / skin / nasal / inhaled / rectal products do not count (except insulin,
# INGREDIENT_ANY_ROUTE). Spelling variants as seen in the DDC list (FRUSEMIDE, TORSEMIDE, ALPRINOLOL).
INGREDIENT_ATC = {
    # A10 — diabetes drugs
    "INSULIN": "A10A",
    "METFORMIN": "A10BA02", "PHENFORMIN": "A10BA01", "BUFORMIN": "A10BA03",
    "GLIBENCLAMIDE": "A10BB01", "GLYBURIDE": "A10BB01", "CHLORPROPAMIDE": "A10BB02", "TOLBUTAMIDE": "A10BB03",
    "TOLAZAMIDE": "A10BB05", "GLIPIZIDE": "A10BB07", "GLIQUIDONE": "A10BB08", "GLICLAZIDE": "A10BB09",
    "GLIMEPIRIDE": "A10BB12",
    "ACARBOSE": "A10BF01", "MIGLITOL": "A10BF02", "VOGLIBOSE": "A10BF03",
    "ROSIGLITAZONE": "A10BG02", "PIOGLITAZONE": "A10BG03",
    "SITAGLIPTIN": "A10BH01", "VILDAGLIPTIN": "A10BH02", "SAXAGLIPTIN": "A10BH03", "ALOGLIPTIN": "A10BH04",
    "LINAGLIPTIN": "A10BH05", "GEMIGLIPTIN": "A10BH06", "EVOGLIPTIN": "A10BH07", "TENELIGLIPTIN": "A10BH08",
    "EXENATIDE": "A10BJ01", "LIRAGLUTIDE": "A10BJ02", "LIXISENATIDE": "A10BJ03", "ALBIGLUTIDE": "A10BJ04",
    "DULAGLUTIDE": "A10BJ05", "SEMAGLUTIDE": "A10BJ06", "ORFORGLIPRON": "A10B",
    "DAPAGLIFLOZIN": "A10BK01", "CANAGLIFLOZIN": "A10BK02", "EMPAGLIFLOZIN": "A10BK03",
    "ERTUGLIFLOZIN": "A10BK04", "IPRAGLIFLOZIN": "A10BK05", "SOTAGLIFLOZIN": "A10BK06",
    "REPAGLINIDE": "A10BX02", "NATEGLINIDE": "A10BX03", "PRAMLINTIDE": "A10BX05", "MITIGLINIDE": "A10BX08",
    "IMEGLIMIN": "A10BX15", "TIRZEPATIDE": "A10BX16",
    # C02 — antihypertensives
    "RESERPINE": "C02AA02", "METHYLDOPA": "C02AB01", "CLONIDINE": "C02AC01", "GUANFACINE": "C02AC02",
    "MOXONIDINE": "C02AC05", "RILMENIDINE": "C02AC06", "PRAZOSIN": "C02CA01", "DOXAZOSIN": "C02CA04",
    "URAPIDIL": "C02CA06", "GUANETHIDINE": "C02CC02", "DIHYDRALAZINE": "C02DB01", "HYDRALAZINE": "C02DB02",
    "MINOXIDIL": "C02DC01",
    "BOSENTAN": "C02KX01", "AMBRISENTAN": "C02KX02", "MACITENTAN": "C02KX04", "RIOCIGUAT": "C02KX05",
    # C03 — diuretics
    "BENDROFLUMETHIAZIDE": "C03AA01", "BENDROFLUAZIDE": "C03AA01", "HYDROFLUMETHIAZIDE": "C03AA02",
    "HYDROCHLOROTHIAZIDE": "C03AA03", "CHLOROTHIAZIDE": "C03AA04", "POLYTHIAZIDE": "C03AA05",
    "CYCLOPENTHIAZIDE": "C03AA07",
    "CLOPAMIDE": "C03BA03", "CHLORTALIDONE": "C03BA04", "CHLORTHALIDONE": "C03BA04", "METOLAZONE": "C03BA08",
    "XIPAMIDE": "C03BA10", "INDAPAMIDE": "C03BA11",
    "FUROSEMIDE": "C03CA01", "FRUSEMIDE": "C03CA01", "BUMETANIDE": "C03CA02", "PIRETANIDE": "C03CA03",
    "TORASEMIDE": "C03CA04", "TORSEMIDE": "C03CA04", "ETHACRYNIC ACID": "C03CC01", "ETACRYNIC ACID": "C03CC01",
    "SPIRONOLACTONE": "C03DA01", "POTASSIUM CANRENOATE": "C03DA02", "CANRENONE": "C03DA03",
    "EPLERENONE": "C03DA04", "FINERENONE": "C03DA05", "AMILORIDE": "C03DB01", "TRIAMTERENE": "C03DB02",
    "TOLVAPTAN": "C03XA01", "CONIVAPTAN": "C03XA02",
    # C07 — beta blockers
    "ALPRENOLOL": "C07AA01", "ALPRINOLOL": "C07AA01", "OXPRENOLOL": "C07AA02", "PINDOLOL": "C07AA03",
    "PROPRANOLOL": "C07AA05", "TIMOLOL": "C07AA06", "SOTALOL": "C07AA07", "NADOLOL": "C07AA12",
    "CARTEOLOL": "C07AA15", "METOPROLOL": "C07AB02", "ATENOLOL": "C07AB03", "ACEBUTOLOL": "C07AB04",
    "BETAXOLOL": "C07AB05", "BISOPROLOL": "C07AB07", "CELIPROLOL": "C07AB08", "ESMOLOL": "C07AB09",
    "NEBIVOLOL": "C07AB12", "LANDIOLOL": "C07AB", "LABETALOL": "C07AG01", "CARVEDILOL": "C07AG02",
    # C08 — calcium channel blockers
    "AMLODIPINE": "C08CA01", "FELODIPINE": "C08CA02", "ISRADIPINE": "C08CA03", "NICARDIPINE": "C08CA04",
    "NIFEDIPINE": "C08CA05", "NIMODIPINE": "C08CA06", "NISOLDIPINE": "C08CA07", "NITRENDIPINE": "C08CA08",
    "LACIDIPINE": "C08CA09", "NILVADIPINE": "C08CA10", "MANIDIPINE": "C08CA11", "BARNIDIPINE": "C08CA12",
    "LERCANIDIPINE": "C08CA13", "CILNIDIPINE": "C08CA14", "BENIDIPINE": "C08CA15", "CLEVIDIPINE": "C08CA16",
    "LEVAMLODIPINE": "C08CA", "VERAPAMIL": "C08DA01", "DILTIAZEM": "C08DB01",
    # C09 — RAAS
    "CAPTOPRIL": "C09AA01", "ENALAPRIL": "C09AA02", "ENALAPRILAT": "C09AA02", "LISINOPRIL": "C09AA03",
    "PERINDOPRIL": "C09AA04", "RAMIPRIL": "C09AA05", "QUINAPRIL": "C09AA06", "BENAZEPRIL": "C09AA07",
    "CILAZAPRIL": "C09AA08", "FOSINOPRIL": "C09AA09", "TRANDOLAPRIL": "C09AA10", "SPIRAPRIL": "C09AA11",
    "DELAPRIL": "C09AA12", "MOEXIPRIL": "C09AA13", "TEMOCAPRIL": "C09AA14", "ZOFENOPRIL": "C09AA15",
    "IMIDAPRIL": "C09AA16",
    "LOSARTAN": "C09CA01", "EPROSARTAN": "C09CA02", "VALSARTAN": "C09CA03", "IRBESARTAN": "C09CA04",
    "CANDESARTAN": "C09CA06", "TELMISARTAN": "C09CA07", "OLMESARTAN": "C09CA08", "AZILSARTAN": "C09CA09",
    "FIMASARTAN": "C09CA10", "ALISKIREN": "C09XA02",
    # C10AA — statins
    "SIMVASTATIN": "C10AA01", "LOVASTATIN": "C10AA02", "PRAVASTATIN": "C10AA03", "FLUVASTATIN": "C10AA04",
    "ATORVASTATIN": "C10AA05", "CERIVASTATIN": "C10AA06", "ROSUVASTATIN": "C10AA07", "PITAVASTATIN": "C10AA08",
    # H02AB — systemic glucocorticoids (budesonide A07/R03, fludrocortisone H02AA: not counted)
    "BETAMETHASONE": "H02AB01", "DEXAMETHASONE": "H02AB02", "FLUOCORTOLONE": "H02AB03",
    "METHYLPREDNISOLONE": "H02AB04", "PARAMETHASONE": "H02AB05", "PREDNISOLONE": "H02AB06",
    "PREDNISONE": "H02AB07", "TRIAMCINOLONE": "H02AB08", "HYDROCORTISONE": "H02AB09", "CORTISONE": "H02AB10",
    "DEFLAZACORT": "H02AB13", "MEPREDNISONE": "H02AB15",
    # N05A — atypical antipsychotics
    "LOXAPINE": "N05AH01", "CLOZAPINE": "N05AH02", "OLANZAPINE": "N05AH03", "QUETIAPINE": "N05AH04",
    "ASENAPINE": "N05AH05", "CLOTIAPINE": "N05AH06",
    "RISPERIDONE": "N05AX08", "ZOTEPINE": "N05AX11", "ARIPIPRAZOLE": "N05AX12", "PALIPERIDONE": "N05AX13",
    "ILOPERIDONE": "N05AX14", "CARIPRAZINE": "N05AX15", "BREXPIPRAZOLE": "N05AX16", "PIMAVANSERIN": "N05AX17",
    "SULPIRIDE": "N05AL01", "TIAPRIDE": "N05AL03", "AMISULPRIDE": "N05AL05", "LEVOSULPIRIDE": "N05AL07",
    "SERTINDOLE": "N05AE03", "ZIPRASIDONE": "N05AE04", "LURASIDONE": "N05AE05",
}
# Counted regardless of route (inhaled insulin is A10 too). Device rows are not drugs.
INGREDIENT_ANY_ROUTE = {"INSULIN"}
INGREDIENT_NOT_A_DRUG = r"DEVICES?|PUMPS?|NEEDLES?|SYRINGES?"

# --------------------------------------------------------------------------
# Labs (LOINC)
# --------------------------------------------------------------------------
LOINC_LAB = {
    "4548-4": "hba1c",          # %
    "17856-6": "hba1c",         # HbA1c (HPLC) %
    "59261-8": "hba1c_ifcc",    # mmol/mol → converted to %
    "1558-6": "fpg",            # mg/dL
    "1521-4": "ogtt_2h",        # mg/dL
    "2345-7": "random_glucose", # mg/dL
    "2339-0": "random_glucose", # Glucose [Mass/volume] in Blood
}

# --------------------------------------------------------------------------
# Observations: source code → canonical concept
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

# When the source sends a free-text concept name (e.g. synthetic data)
OBS_NAME_TO_CONCEPT = {
    "bmi": "bmi", "height_cm": "height_cm", "weight_kg": "weight_kg",
    "waist_cm": "waist_cm", "hip_cm": "hip_cm", "systolic_bp": "sbp",
    "diastolic_bp": "dbp", "smoking_status": "smoking_status",
    "alcohol_use": "alcohol_use", "pack_years": "pack_years",
    "self_rated_health": "self_rated_health",
}

# Smoking status free text → QDiabetes category
# 0 non, 1 ex, 2 light, 3 moderate, 4 heavy. "current" without intensity → None (decision: config)
SMOKING_TEXT_TO_CAT = {
    "never": 0, "non": 0, "non-smoker": 0, "nonsmoker": 0,
    "ex": 1, "former": 1, "ex-smoker": 1,
    "light": 2, "moderate": 3, "heavy": 4,
    "current": None,
}

# --------------------------------------------------------------------------
# Ethnicity mappings  [DECISION PENDING — medical team approval]
# --------------------------------------------------------------------------
# QDiabetes 9 categories: WhiteNA (white or not recorded — combined in the source code), Indian, Pakistani,
# Bangladeshi, OtherAsian, BlackCaribbean, BlackAfrican, Chinese, Other.
# Emirati / Gulf Arab / Arab → "Other": no equivalent in the UK model (core gap target).
NABIDH_TO_QDIABETES = {
    "indian": "Indian",
    "pakistani": "Pakistani",
    "bangladeshi": "Bangladeshi",
    "other asian": "OtherAsian",
    "filipino": "OtherAsian",
    "sri lankan": "OtherAsian",
    "nepali": "OtherAsian",
    "chinese": "Chinese",
    "african": "BlackAfrican",
    "black african": "BlackAfrican",
    "black caribbean": "BlackCaribbean",
    "western": "WhiteNA",
    "white": "WhiteNA",
    "european": "WhiteNA",
    "not recorded": "WhiteNA",     # QDiabetes: "White or not recorded"
    "unknown": "WhiteNA",
    "emirati": "Other",
    "gulf arab (non-emirati)": "Other",
    "arab (non-gulf)": "Other",
    "arab": "Other",
    "other": "Other",
    "other (unmapped nationality)": "Other",
}
QDIABETES_ETHNICITIES = ["WhiteNA", "Indian", "Pakistani", "Bangladeshi", "OtherAsian",
                         "BlackCaribbean", "BlackAfrican", "Chinese", "Other"]
# Leicester: white = 0, all other groups non-white (LRA 2010: 6 points; LPRS 2012: BME = 1)
LRS_WHITE = {"western", "white", "european"}
ETHNICITY_UNKNOWN = {"not recorded", "unknown", "", "not stated", "na", "n/a"}


# --------------------------------------------------------------------------
# Nationality → ethnic group  [DECIDED: 2026-11-13 source = nationality; mapping content DECISION PENDING — D6]
# --------------------------------------------------------------------------
# With PARAMS["ethnicity_source"] = "nationality" the ethnic group is derived from nationality. The groups are the
# labels of the NABIDH ethnicity dictionary above, so the QDiabetes / LRS mapping and subgroup analyses
# stay the same. Nationality is not ethnicity (e.g. a UK citizen of Indian origin) — known limitation.
# Only clear-cut cases are mapped. Ambiguous nationalities (Iran, Afghanistan, Turkey, Sudan, South Africa,
# Latin America, Central Asia …) are deliberately unmapped: "Other (unmapped nationality)" → QDiabetes "Other",
# LRS non-white; visible in the ingest report, added here once the medical team decides.
# Row: (group, ISO3, ISO2, [name / adjective variants]) — all lower-cased to become keys.
NATIONALITY_COUNTRIES = [
    ("Emirati", "ARE", "AE", ["united arab emirates", "uae", "u.a.e.", "emirati", "uae national"]),
    ("Gulf Arab (non-Emirati)", "SAU", "SA", ["saudi arabia", "saudi", "saudi arabian", "ksa"]),
    ("Gulf Arab (non-Emirati)", "KWT", "KW", ["kuwait", "kuwaiti"]),
    ("Gulf Arab (non-Emirati)", "QAT", "QA", ["qatar", "qatari"]),
    ("Gulf Arab (non-Emirati)", "BHR", "BH", ["bahrain", "bahraini"]),
    ("Gulf Arab (non-Emirati)", "OMN", "OM", ["oman", "omani"]),
    ("Arab (non-Gulf)", "EGY", "EG", ["egypt", "egyptian"]),
    ("Arab (non-Gulf)", "JOR", "JO", ["jordan", "jordanian"]),
    ("Arab (non-Gulf)", "LBN", "LB", ["lebanon", "lebanese"]),
    ("Arab (non-Gulf)", "SYR", "SY", ["syria", "syrian", "syrian arab republic"]),
    ("Arab (non-Gulf)", "IRQ", "IQ", ["iraq", "iraqi"]),
    ("Arab (non-Gulf)", "YEM", "YE", ["yemen", "yemeni"]),
    ("Arab (non-Gulf)", "PSE", "PS", ["palestine", "palestinian", "state of palestine"]),
    ("Arab (non-Gulf)", "MAR", "MA", ["morocco", "moroccan"]),
    ("Arab (non-Gulf)", "DZA", "DZ", ["algeria", "algerian"]),
    ("Arab (non-Gulf)", "TUN", "TN", ["tunisia", "tunisian"]),
    ("Arab (non-Gulf)", "LBY", "LY", ["libya", "libyan"]),
    ("Indian", "IND", "IN", ["india", "indian"]),
    ("Pakistani", "PAK", "PK", ["pakistan", "pakistani"]),
    ("Bangladeshi", "BGD", "BD", ["bangladesh", "bangladeshi"]),
    ("Filipino", "PHL", "PH", ["philippines", "filipino", "filipina", "philippine"]),
    ("Other Asian", "LKA", "LK", ["sri lanka", "sri lankan"]),
    ("Other Asian", "NPL", "NP", ["nepal", "nepali", "nepalese"]),
    ("Other Asian", "IDN", "ID", ["indonesia", "indonesian"]),
    ("Other Asian", "MYS", "MY", ["malaysia", "malaysian"]),
    ("Other Asian", "THA", "TH", ["thailand", "thai"]),
    ("Other Asian", "VNM", "VN", ["vietnam", "viet nam", "vietnamese"]),
    ("Other Asian", "MMR", "MM", ["myanmar", "burmese"]),
    ("Other Asian", "BTN", "BT", ["bhutan", "bhutanese"]),
    ("Other Asian", "MDV", "MV", ["maldives", "maldivian"]),
    ("Other Asian", "JPN", "JP", ["japan", "japanese"]),
    ("Other Asian", "KOR", "KR", ["south korea", "korea", "republic of korea", "korean"]),
    ("Chinese", "CHN", "CN", ["china", "chinese"]),
    ("Chinese", "HKG", "HK", ["hong kong"]),
    ("Chinese", "TWN", "TW", ["taiwan", "taiwanese"]),
    ("African", "NGA", "NG", ["nigeria", "nigerian"]),
    ("African", "GHA", "GH", ["ghana", "ghanaian"]),
    ("African", "KEN", "KE", ["kenya", "kenyan"]),
    ("African", "UGA", "UG", ["uganda", "ugandan"]),
    ("African", "ETH", "ET", ["ethiopia", "ethiopian"]),
    ("African", "ERI", "ER", ["eritrea", "eritrean"]),
    ("African", "SOM", "SO", ["somalia", "somali"]),
    ("African", "TZA", "TZ", ["tanzania", "tanzanian"]),
    ("African", "CMR", "CM", ["cameroon", "cameroonian"]),
    ("African", "ZWE", "ZW", ["zimbabwe", "zimbabwean"]),
    ("African", "ZMB", "ZM", ["zambia", "zambian"]),
    ("African", "SEN", "SN", ["senegal", "senegalese"]),
    ("Black Caribbean", "JAM", "JM", ["jamaica", "jamaican"]),
    ("Black Caribbean", "TTO", "TT", ["trinidad and tobago", "trinidadian"]),
    ("Black Caribbean", "BRB", "BB", ["barbados", "barbadian"]),
    ("Western", "GBR", "GB", ["united kingdom", "uk", "great britain", "british", "england", "english"]),
    ("Western", "IRL", "IE", ["ireland", "irish"]),
    ("Western", "USA", "US", ["united states", "united states of america", "usa", "american"]),
    ("Western", "CAN", "CA", ["canada", "canadian"]),
    ("Western", "AUS", "AU", ["australia", "australian"]),
    ("Western", "NZL", "NZ", ["new zealand", "new zealander"]),
    ("Western", "FRA", "FR", ["france", "french"]),
    ("Western", "DEU", "DE", ["germany", "german"]),
    ("Western", "ITA", "IT", ["italy", "italian"]),
    ("Western", "ESP", "ES", ["spain", "spanish"]),
    ("Western", "PRT", "PT", ["portugal", "portuguese"]),
    ("Western", "NLD", "NL", ["netherlands", "dutch"]),
    ("Western", "BEL", "BE", ["belgium", "belgian"]),
    ("Western", "CHE", "CH", ["switzerland", "swiss"]),
    ("Western", "AUT", "AT", ["austria", "austrian"]),
    ("Western", "SWE", "SE", ["sweden", "swedish"]),
    ("Western", "NOR", "NO", ["norway", "norwegian"]),
    ("Western", "DNK", "DK", ["denmark", "danish"]),
    ("Western", "FIN", "FI", ["finland", "finnish"]),
    ("Western", "POL", "PL", ["poland", "polish"]),
    ("Western", "GRC", "GR", ["greece", "greek"]),
    ("Western", "ROU", "RO", ["romania", "romanian"]),
    ("Western", "RUS", "RU", ["russia", "russian", "russian federation"]),
    ("Western", "UKR", "UA", ["ukraine", "ukrainian"]),
]
NATIONALITY_TO_GROUP = {
    key: group
    for group, iso3, iso2, names in NATIONALITY_COUNTRIES
    for key in [iso3.lower(), iso2.lower(), *names]
}
UNMAPPED_NATIONALITY = "Other (unmapped nationality)"

# PARAMS["ethnicity_source"] → column in the patients table
ETHNICITY_SOURCE_COLUMN = {"nationality": "nationality", "ethnicity": "ethnicity_raw"}


def ethnic_group(raw: pd.Series, source: str) -> pd.Series:
    """Source value (nationality or NABIDH ethnicity) → ethnic group label used in the analysis.

    source="ethnicity": the value is returned as is. source="nationality": NATIONALITY_TO_GROUP;
    recorded but unmappable nationality → UNMAPPED_NATIONALITY. Not recorded (NA) → NA.
    """
    if source == "ethnicity":
        return raw
    if source != "nationality":
        raise ValueError(f"Unknown ethnicity_source: {source}")
    key = raw.astype("string").str.strip().str.lower()
    grp = key.map(NATIONALITY_TO_GROUP).astype(object)
    # "string" dtype: unrecorded values stay NA (same behaviour as the ethnicity source, e.g. .eq() → NA)
    return grp.where(key.isna() | grp.notna(), UNMAPPED_NATIONALITY).where(key.notna()).astype("string")


def map_ethnicity_qdiabetes(raw: pd.Series) -> pd.Series:
    """NABIDH raw category → QDiabetes category. Unmappable → 'Other' (reported)."""
    key = raw.astype("string").str.strip().str.lower()
    out = key.map(NABIDH_TO_QDIABETES)
    out = out.where(key.notna(), "WhiteNA")       # completely empty = not recorded
    return out.fillna("Other")


# --------------------------------------------------------------------------
# 8 core variables (revised MVP) + LRA 2010 extra variable (LPRS 2012 needs no waist — K-LRS)
# --------------------------------------------------------------------------
CORE_VARIABLES = [
    "sex", "age", "ethnicity", "bmi", "smoking", "family_history", "cvd", "hypertension",
]


# --------------------------------------------------------------------------
# Matching helpers
# --------------------------------------------------------------------------
def norm_icd(code: pd.Series) -> pd.Series:
    """Normalise an ICD-10 code for comparison: upper case, no dots/spaces."""
    return code.astype("string").str.upper().str.replace(r"[.\s]", "", regex=True)


def match_dx(conditions: pd.DataFrame, group: str) -> pd.Series:
    """Return whether each conditions row matches the given diagnosis group (bool Series)."""
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
    """Flat list for NB0's 'requested vs received' mapping."""
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
