"""notebooks/*.py (percent format) → .ipynb. Needs no extra package.

Usage:  python tools/py2ipynb.py notebooks/00_data_profile.py
The source (single source of truth) is the .py file; the .ipynb is a derived output and stays out of git.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def convert(src: Path) -> Path:
    text = src.read_text(encoding="utf-8")
    # drop the jupytext header
    text = re.sub(r"\A# ---\n(?:#.*\n)*?# ---\n", "", text)
    cells, cur, kind = [], [], None

    def flush():
        if kind is None:
            return
        body = "\n".join(cur).strip("\n")
        if kind == "markdown":
            body = "\n".join(line[2:] if line.startswith("# ") else line.lstrip("#") for line in body.splitlines())
        if body.strip():
            src_lines = [line + "\n" for line in body.splitlines()]
            src_lines[-1] = src_lines[-1].rstrip("\n")
            cell = {"cell_type": kind, "metadata": {}, "source": src_lines}
            if kind == "code":
                cell.update({"execution_count": None, "outputs": []})
            cells.append(cell)

    for line in text.splitlines():
        if line.startswith("# %%"):
            flush()
            kind, cur = ("markdown" if "[markdown]" in line else "code"), []
        else:
            cur.append(line)
    flush()
    nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python",
                                                      "name": "python3"}},
          "nbformat": 4, "nbformat_minor": 5}
    out = src.with_suffix(".ipynb")
    out.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(convert(Path(arg)))
