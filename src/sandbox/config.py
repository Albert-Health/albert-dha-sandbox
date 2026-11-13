"""Merkezi konfigürasyon.

Tüm analiz parametreleri burada. Değişiklikler audit log'a otomatik yazılır
(audit.Run, bu modüldeki PARAMS sözlüğünü kaydeder).

Kaynak belgeler:
- MVP Dataset v1.0 (kod listeleri)
- Interim Data Assessment (C1/C2 tanımı, cap = 2,600)
- Non-Diabetic Cohort Spec v2 (C3: index, lookback, takip, outcome)
"""
from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------
# Yollar
# --------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = {
    "synthetic": DATA_DIR / "synthetic" / "raw",
    "nabidh": DATA_DIR / "nabidh" / "raw",
}
CANONICAL_DIR = DATA_DIR / "canonical"          # canonical/<source>/<cohort>/
OUTPUT_DIR = REPO_ROOT / "outputs"
AUDIT_DIR = OUTPUT_DIR / "audit"

COHORTS = ("c1", "c2", "c3")

# --------------------------------------------------------------------------
# Analiz parametreleri (tek doğruluk kaynağı)
# --------------------------------------------------------------------------
PARAMS = {
    # Genel
    "seed": 42,
    "age_min": 25,                    # QDiabetes geçerli aralık
    "age_max": 84,

    # Etnisite kaynağı: "nationality" (uyruk) | "ethnicity" (NABIDH etnisite alanı).
    # [KARAR: 2026-11-13, ensargunesdogdu] Etnisite yerine uyruk kullanılacak. Uyruk → etnik grup
    # eşlemesinin içeriği (codelists.NATIONALITY_COUNTRIES) ayrıca [KARAR BEKLİYOR] (D6).
    "ethnicity_source": "nationality",

    # Glisemik eşikler (ADA 2024) — mg/dL ve %
    "hba1c_dm": 6.5,
    "hba1c_pre_low": 5.7,
    "fpg_dm": 126.0,
    "fpg_pre_low": 100.0,
    "ogtt_dm": 200.0,
    "ogtt_pre_low": 140.0,
    "random_glucose_dm": 200.0,

    # C1 / C2 (Interim Data Assessment)
    "c1_cap": 2600,
    "c2_cap": 2600,
    # C1 tamlık tanımı: aile öyküsü / KVH / HT kodları "var/yok" olarak ele alınır.
    # True → aile öyküsü için kayıt (FamilyHistory pozitif/negatif veya Z83.3) şartı aranır.
    # [KARAR BEKLİYOR] D17 — enclave'de NABIDH'in C1 tanımı görülünce netleşecek.
    "c1_require_fh_record": False,

    # C3 (Non-Diabetic Cohort Spec v2)
    # v2 belgesinin iki sürümü çelişiyor: 24 ay (ilk sürüm) vs 12 ay (2026-11-13).
    # [KARAR: 2026-11-13, ensargunesdogdu] D3: 1 yıl birincil; 2 yıl (730 gün) ek kontrol olarak duyarlılık
    # çalıştırması: SANDBOX_PARAMS='{"predictor_lookback_days": 730}' (.run "4c").
    "predictor_lookback_days": 365,
    "min_followup_gap_days": 0,       # v2 alt sürümü ">= 3 ay" önerir; 0 = şart yok
    # [KARAR: 2026-11-13, ensargunesdogdu] D2: birincil horizon 3 yıl "şimdilik" — ayrıntılı
    # değerlendirilecek. 5 yıl ikincil horizon olarak raporlanmaya devam eder.
    "horizon_years": 3,               # birincil
    "horizon_years_fallback": 5,      # ikincil (NB2'de CI'sız raporlanır)
    "c3_cap": None,                   # v2: "no cap"
    # Index'ten sonraki N gün içinde olay = başlangıçta zaten diyabetik (tanı konmamış) kabul edilir
    # ve hasta kohorttan çıkarılır. NB0 duyarlılık tablosu 0/90/180 raporlar.
    # [KARAR: 2026-11-13, ensargunesdogdu] D1: 90 gün (v2'de washout yoktu; 0 = v2 duyarlılığı, .run "4b").
    "outcome_washout_days": 90,

    # QDiabetes-2018 Model A (scores/qdiabetes2018a.py) — [KARAR BEKLİYOR] işaretliler medikal ekipte
    # Revize MVP yalnızca 8 çekirdek değişkeni istiyor → steroid, statin, atipik antipsikotik,
    # şizofreni/bipolar, öğrenme güçlüğü, GDM, PCOS = 0 ("indirgenmiş Model A"). False → veride varsa kullanılır.
    "qd_force_reduced_model": True,          # [KARAR: 2026-11-13, ensargunesdogdu] D9: kapsam dışı kalacak
    "qd_townsend": 0.0,                      # [KARAR: 2026-11-13, ensargunesdogdu] D10: out of scope → 0
    "qd_smoking_current_category": 3,        # yoğunluksuz "current" → 3=moderate [KARAR BEKLİYOR] D7
    # [KARAR: 2026-11-13, ensargunesdogdu] D8: sigara kaydı yok = bilinmiyor (non-smoker sayılmaz) →
    # QDiabetes hesaplanmaz, eksiklik nedeni "smoking_missing" olarak raporlanır.
    "qd_missing_smoking_as_non": False,
    # Kaynak kod yalnızca 10 yıllık baseline survival verir. Diğer horizon'lar için
    # S0(t) = S0(10)^(t/10) (sabit baseline hazard varsayımı) [KARAR BEKLİYOR]
    "qd_baseline_time_scaling": "power",
    # sens/spec/PPV için horizon riski eşiği (%). [KARAR: 2026-11-13, ensargunesdogdu] D5: şimdilik
    # varsayılan (None) → eşik KPI'ları "Pending".
    "qd_risk_threshold_pct": None,

    # Leicester Risk Assessment (scores/lrs.py)
    "lrs_high_risk_threshold": 16,           # ≥16 yüksek risk (NHS Health Check pratik kılavuzu)
    "lrs_unknown_ethnicity_as_missing": True,  # "Not recorded" → skor hesaplanmaz [KARAR BEKLİYOR]

    # Recalibration (Kol 2)
    "recal_split": "temporal",               # "temporal" (index tarihine göre) | "random"
    "recal_train_frac": 0.7,

    # Alt-gruplar
    "age_band_edges": [25, 40, 55, 70, 85],  # [25,40) [40,55) [55,70) [70,85)
    "age_band_labels": ["25–39", "40–54", "55–69", "70–84"],

    # Manuel KPI girdisi
    "security_incidents": 0,                 # Data Security KPI — enclave olay kaydından manuel

    # İstatistik
    "bootstrap_reps": 500,
    "min_events_subgroup": 50,
    "small_cell_threshold": 10,       # çıktı tablolarında n < 10 → "<10"
}
