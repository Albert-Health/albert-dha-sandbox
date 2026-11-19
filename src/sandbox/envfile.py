"""`.env` at the repo root → os.environ. A local convenience, so you need not type `export` in every terminal.

`.env` is untracked (.gitignore) and never enters the repo (AGENTS.md rules 1-2). `import sandbox` loads it once, so
notebooks, the Jupyter kernel, tools/ and `enclave.sh` all see the same values. Typical content (VM):

    SANDBOX_SOURCE=nabidh
    NABIDH_IRIS_PASSWORD=...

Format: `KEY=VALUE` lines. Blank lines and lines starting with `#` are skipped. An `export ` prefix is allowed, so
bash can also read the file with `set -a; . ./.env; set +a`. If a value is wrapped in matching quotes (single or
double), the quotes are dropped. No variable expansion and no end-of-line comments: a password may contain `#` or `$`.

Precedence: an environment variable that is already set is not overwritten. A value given on the command line
(`SANDBOX_SOURCE=synthetic python ...`, `SANDBOX_PARAMS=...`) always beats `.env`.
Only the NAMES of keys from `.env` go to the audit, never their values.

SANDBOX_ENV_FILE: a different file. If empty or "none", nothing is loaded.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ENV_FILE_VAR = "SANDBOX_ENV_FILE"
DEFAULT_PATH = Path(__file__).resolve().parents[2] / ".env"
_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Summary of the last load (for audit and diagnostics; holds no values)
LOADED: dict = {"path": None, "keys": []}


def parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        if not _KEY.match(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def path() -> Path | None:
    v = os.environ.get(ENV_FILE_VAR)
    if v is None:
        return DEFAULT_PATH
    v = v.strip()
    return None if v.lower() in ("", "none") else Path(v).expanduser()


def load(file: Path | None = None, override: bool = False) -> list[str]:
    """Reads `.env` and adds keys not already in the environment. → names of the added keys."""
    file = Path(file) if file is not None else path()
    if file is None or not file.is_file():
        return []
    try:
        values = parse(file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        print(f"WARNING: cannot read {file} ({type(e).__name__}); .env ignored", file=sys.stderr)
        return []
    added = [k for k in values if override or k not in os.environ]
    for k in added:
        os.environ[k] = values[k]
    LOADED.update(path=str(file), keys=sorted(set(LOADED["keys"]) | set(added)))
    return added
