"""Çıktı ifşa kontrolü (statistical disclosure control).

Kod yalnızca enclave içinde çalışır; bu modülün amacı enclave'den çıkacak
özet tablolarda küçük hücreleri bastırmaktır (DHA veri paylaşım şartları).
"""
from __future__ import annotations

import pandas as pd

from .config import PARAMS


def suppress_rates(df: pd.DataFrame, num_col: str, den_cols, rate_cols,
                   threshold: int | None = None) -> pd.DataFrame:
    """Pay ya da (payda − pay) 0 < x < threshold olan satırlarda oran sütunlarını bastırır.

    Bastırılmış sayımın "oran × payda" ile geri hesaplanmasını önler. Sayımlar suppress_small_counts
    ile bastırılmadan ÖNCE (sayılar hâlâ sayısalken) çağrılmalı.
    """
    threshold = threshold or PARAMS["small_cell_threshold"]
    out = df.copy()
    k = pd.to_numeric(out[num_col], errors="coerce")

    def small(s: pd.Series) -> pd.Series:
        return s.notna() & (s > 0) & (s < threshold)

    mask = small(k)
    for d in den_cols:
        mask |= small(pd.to_numeric(out[d], errors="coerce") - k)
    for c in rate_cols:
        out[c] = out[c].astype(object)
        out.loc[mask, c] = f"suppressed (<{threshold})"
    return out


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
