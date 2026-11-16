"""Audit trail (KPI: Audit Trail Completeness = %100, Critical).

Her çalıştırma bir Run'dır. Run şunları kaydeder:
- run_id, başlangıç/bitiş zamanı, kullanıcı, makine, Python ve paket sürümleri
- kod parmak izi: src/ altındaki tüm .py dosyalarının SHA-256'sı + git commit (varsa)
- girdi dosyalarının yolu, boyutu, SHA-256'sı
- PARAMS (config) anlık görüntüsü
- yazılan her çıktı dosyasının yolu ve SHA-256'sı
- serbest olay kayıtları (adım adım ne yapıldı)

Yazım yeri: outputs/audit/audit_log.jsonl (append-only) ve
outputs/<run_id>/run_manifest.json. Ağ erişimi yoktur, her şey yereldir.
"""
from __future__ import annotations

import atexit
import datetime as _dt
import getpass
import hashlib
import json
import platform
import subprocess
import sys
import uuid
from pathlib import Path

from .config import AUDIT_DIR, OUTPUT_DIR, PARAMS, REPO_ROOT


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def code_fingerprint() -> dict:
    files = sorted((REPO_ROOT / "src").rglob("*.py")) + sorted((REPO_ROOT / "notebooks").glob("*.py"))
    per_file = {str(f.relative_to(REPO_ROOT)): sha256_file(f) for f in files}
    combined = hashlib.sha256("".join(per_file[k] for k in sorted(per_file)).encode()).hexdigest()
    git = None
    try:
        git = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=5).stdout.strip() or None
        dirty = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--", "src", "notebooks"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        git = {"commit": git, "dirty": bool(dirty)}
    except Exception:  # git yoksa audit yine çalışır
        pass
    return {"combined_sha256": combined, "files": per_file, "git": git}


def _versions() -> dict:
    out = {"python": sys.version.split()[0]}
    for mod in ("numpy", "pandas", "matplotlib"):
        try:
            out[mod] = __import__(mod).__version__
        except Exception:
            out[mod] = None
    # Opsiyonel IRIS sürücüleri (io/iris.py): yalnızca kuruluysa, import etmeden
    from importlib import metadata
    for dist in ("intersystems-irispython", "pyodbc"):
        try:
            out[dist] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            pass
    return out


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class Run:
    def __init__(self, name: str, params: dict | None = None, source: str | None = None):
        ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")   # UTC: makineden bağımsız sıralama
        self.run_id = f"{ts}_{name}_{uuid.uuid4().hex[:6]}"
        self.name = name
        self.dir = OUTPUT_DIR / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        self.record = {
            "run_id": self.run_id, "name": name, "source": source, "status": "running", "started_utc": _now(),
            "user": getpass.getuser(), "host": platform.node(), "platform": platform.platform(),
            "versions": _versions(), "code": code_fingerprint(),
            "params": dict(params or PARAMS), "inputs": [], "outputs": [], "events": [],
        }
        self._append({"event": "run_start", "run_id": self.run_id, "name": name,
                      "code_sha256": self.record["code"]["combined_sha256"], "ts": _now()})
        self._finished = False
        # Script hata ile biterse de run_end yazılsın (audit trail boşluk bırakmasın)
        atexit.register(self._close_if_open)

    def _close_if_open(self) -> None:
        if not self._finished:
            self.finish(status="failed_or_interrupted")

    # -- kayıtlar ---------------------------------------------------------
    def _append(self, obj: dict) -> None:
        with open(AUDIT_DIR / "audit_log.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, default=str, ensure_ascii=False) + "\n")

    def log(self, message: str, **data) -> None:
        ev = {"ts": _now(), "message": message, **data}
        self.record["events"].append(ev)
        self._append({"event": "log", "run_id": self.run_id, **ev})

    def add_inputs(self, paths) -> None:
        for p in paths:
            p = Path(p)
            if p.is_dir():
                self.add_inputs(sorted(x for x in p.rglob("*") if x.is_file()))
                continue
            item = {"path": str(p.relative_to(REPO_ROOT)) if p.is_relative_to(REPO_ROOT) else str(p),
                    "bytes": p.stat().st_size, "sha256": sha256_file(p)}
            self.record["inputs"].append(item)
            self._append({"event": "input", "run_id": self.run_id, **item})

    def add_query_input(self, target: str, query: str, rows: int, sha256: str, label: str = "") -> None:
        """Dosya olmayan girdi (IRIS sorgusu): hedef (host:port/NAMESPACE — şifre / parametre yok),
        çalıştırılan SELECT, satır sayısı ve sonucun (CSV metni) SHA-256'sı."""
        item = {"query": query, "target": target, "rows": int(rows), "sha256": sha256, "label": label}
        self.record["inputs"].append(item)
        self._append({"event": "input", "run_id": self.run_id, **item})

    def path(self, relname: str) -> Path:
        p = self.dir / relname
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def register_output(self, path: Path, description: str = "") -> Path:
        path = Path(path)
        item = {"path": str(path.relative_to(REPO_ROOT)), "sha256": sha256_file(path),
                "bytes": path.stat().st_size, "description": description}
        self.record["outputs"].append(item)
        self._append({"event": "output", "run_id": self.run_id, **item})
        return path

    def save_table(self, df, relname: str, description: str = "", index: bool = False) -> Path:
        p = self.path(relname)
        df.to_csv(p, index=index, encoding="utf-8")
        return self.register_output(p, description)

    def save_figure(self, fig, relname: str, description: str = "") -> Path:
        p = self.path(relname)
        fig.savefig(p, dpi=120, bbox_inches="tight")
        return self.register_output(p, description)

    def save_json(self, obj, relname: str, description: str = "") -> Path:
        p = self.path(relname)
        p.write_text(json.dumps(obj, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        return self.register_output(p, description)

    def finish(self, status: str = "success") -> Path:
        self._finished = True
        self.record["status"] = status
        self.record["finished_utc"] = _now()
        manifest = self.dir / "run_manifest.json"
        manifest.write_text(json.dumps(self.record, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        self._append({"event": "run_end", "run_id": self.run_id, "status": status,
                      "n_outputs": len(self.record["outputs"]), "ts": _now(),
                      "manifest_sha256": sha256_file(manifest)})
        return manifest
