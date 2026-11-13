"""Çıktı ifşa kontrolü (statistical disclosure control).

Kod yalnızca enclave içinde çalışır; bu modülün amacı enclave'den çıkacak
özet tablolarda küçük hücreleri bastırmaktır (DHA veri paylaşım şartları).
"""
from __future__ import annotations

import pandas as pd

from .config import PARAMS


def suppress_small_counts(df: pd.DataFrame, count_cols, threshold: int | None = None) -> pd.DataFrame:
    """count_cols içindeki 0 < n < threshold değerlerini '<threshold' ile değiştirir."""
    threshold = threshold or PARAMS["small_cell_threshold"]
    out = df.copy()
    for c in count_cols:
        s = pd.to_numeric(out[c], errors="coerce")
        mask = s.notna() & (s > 0) & (s < threshold)
        out[c] = out[c].astype(object)
        out.loc[mask, c] = f"<{threshold}"
    return out
