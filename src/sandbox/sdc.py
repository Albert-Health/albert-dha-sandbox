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


def collapse_rare_rows(df: pd.DataFrame, count_cols, label_cols, by=None, threshold: int | None = None,
                       label: str | None = None) -> pd.DataFrame:
    """Rows whose every count in count_cols is under the threshold → one row per `by` group, labels replaced.

    For tables that list source values (e.g. ethnicity labels) next to counts: a label seen in fewer than
    `threshold` patients in every cohort is not printed at all; its counts are added into the merged row. Call it
    BEFORE suppress_small_counts (while the counts are numeric)."""
    threshold = threshold or PARAMS["small_cell_threshold"]
    label = label or f"(values with < {threshold} patients each)"
    counts = df[list(count_cols)].apply(pd.to_numeric, errors="coerce").fillna(0)
    rare = (counts < threshold).all(axis=1)
    keep, small = df[~rare], df[rare]
    if small.empty:
        return df.reset_index(drop=True)
    by = list(by or [])
    groups = small.groupby(by, sort=False) if by else [((), small)]
    merged = []
    for key, g in groups:
        row = {c: label for c in label_cols}
        row.update(dict(zip(by, key if isinstance(key, tuple) else (key,))))
        row.update({c: int(pd.to_numeric(g[c], errors="coerce").fillna(0).sum()) for c in count_cols})
        merged.append(row)
    return pd.concat([keep, pd.DataFrame(merged)], ignore_index=True)


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
