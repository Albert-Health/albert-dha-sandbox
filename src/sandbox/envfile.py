"""Repo kökündeki `.env` → os.environ. Yerel kolaylık: her terminalde `export` yazmamak için.

`.env` git dışıdır (.gitignore) ve repoya girmez (AGENTS.md kural 1-2). `import sandbox` onu bir kez yükler; bu
yüzden notebook'lar, Jupyter kernel'i, tools/ ve `enclave.sh` aynı değerleri görür. Tipik içerik (VM):

    SANDBOX_SOURCE=nabidh
    NABIDH_IRIS_PASSWORD=...

Biçim: `KEY=VALUE` satırları. Boş satır ve `#` ile başlayan satır atlanır. `export ` öneki olabilir; böylece dosya
bash'te `set -a; . ./.env; set +a` ile de okunur. Değer aynı tırnakla (tek ya da çift) sarılıysa tırnak atılır.
Değişken genişletme ve satır sonu yorumu yoktur: şifrede `#` ya da `$` olabilir.

Öncelik: zaten ayarlı ortam değişkeni ezilmez. Komut satırında verilen değer
(`SANDBOX_SOURCE=synthetic python ...`, `SANDBOX_PARAMS=...`) her zaman `.env`'i geçer.
Audit'e yalnız `.env`'den gelen anahtarların ADLARI yazılır, değerleri asla.

SANDBOX_ENV_FILE: başka bir dosya. Boş ya da "none" verilirse yükleme yapılmaz.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ENV_FILE_VAR = "SANDBOX_ENV_FILE"
DEFAULT_PATH = Path(__file__).resolve().parents[2] / ".env"
_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Son yüklemenin özeti (audit ve teşhis için; değer içermez)
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
    """`.env`'i okur, ortamda olmayan anahtarları ekler. → eklenen anahtarların adları."""
    file = Path(file) if file is not None else path()
    if file is None or not file.is_file():
        return []
    try:
        values = parse(file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        print(f"UYARI: {file} okunamadı ({type(e).__name__}); .env yok sayıldı", file=sys.stderr)
        return []
    added = [k for k in values if override or k not in os.environ]
    for k in added:
        os.environ[k] = values[k]
    LOADED.update(path=str(file), keys=sorted(set(LOADED["keys"]) | set(added)))
    return added
