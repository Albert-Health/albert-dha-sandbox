"""Output disclosure control (statistical disclosure control).

The code runs only inside the enclave; this module suppresses small cells in the
summary tables that leave the enclave (DHA data-sharing terms).
"""
from __future__ import annotations

import pandas as pd

from .config import PARAMS


def suppress_rates(df: pd.DataFrame, num_col: str, den_cols, rate_cols,
                   threshold: int | None = None) -> pd.DataFrame:
    """Suppresses the rate columns in rows where the numerator or (denominator − numerator) is 0 < x < threshold.

    Prevents back-calculating a suppressed count as "rate × denominator". Call it BEFORE the counts are
    suppressed with suppress_small_counts (while they are still numeric).
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


def fmt_count(n, threshold: int | None = None) -> str:
    """One count → text: '<threshold' if 0 < n < threshold (for summaries printed to the terminal)."""
    threshold = threshold or PARAMS["small_cell_threshold"]
    try:
        v = int(n)
    except (TypeError, ValueError):
        return str(n)
    return f"<{threshold}" if 0 < v < threshold else str(v)


def suppress_small_counts(df: pd.DataFrame, count_cols, threshold: int | None = None) -> pd.DataFrame:
    """Replaces values 0 < n < threshold in count_cols with '<threshold'."""
    threshold = threshold or PARAMS["small_cell_threshold"]
    out = df.copy()
    for c in count_cols:
        s = pd.to_numeric(out[c], errors="coerce")
        mask = s.notna() & (s > 0) & (s < threshold)
        out[c] = out[c].astype(object)
        out.loc[mask, c] = f"<{threshold}"
    return out
