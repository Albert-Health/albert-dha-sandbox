"""Ortam kontrolü: bu makinede (enclave VM'i ya da yerel) projenin çalışması için gereken her şey var mı?

Kullanım:
  python tools/check_environment.py                   # hepsi; IRIS bağlantı ayarı varsa IRIS de
  python tools/check_environment.py --iris            # IRIS zorunlu: ayar / sürücü / bağlantı yoksa FAIL
  python tools/check_environment.py --iris-sqlite data/nabidh_dryrun/iris     # IRIS yerine SQLite (prova)
  python tools/check_environment.py --github          # GitHub'a erişim (git ls-remote origin)
  python tools/check_environment.py --quick           # unit testleri ve pip check'i atla

Gruplar (FAIL = proje bu ortamda çalışmaz; WARN = eksik ama engel değil):
  python     Python ≥ 3.10, pip, venv, başlık dosyaları ve derleyici (python3-dev, build-essential)
  core       requirements.txt paketleri kurulu, sürüm aralığında ve import ediliyor (IRIS sürücüsü dahil)
  repo       git, commit, çalışma ağacı; data/ ve outputs/ yazılabilir
  iris       sürücü (intersystems-irispython; yedek pyodbc), bağlantı ayarları, TCP, bağlantı + SELECT 1
  mapping    adapter SOURCES / IRIS_COHORTS tabloları ve sütunları IRIS'te var mı (satır okunmaz).
             Eksikler WARN: ortam sorunu değil, nabidh.py'de düzeltilecek eşleme — ama ingest o hâliyle çalışmaz
  explore    requirements-explore.txt: keşif paketleri (Jupyter, scipy, polars …) — projenin bağımlılığı değil
  desktop    masaüstü oturumu, IntelliJ, tarayıcı (yalnız Linux'ta WARN)
  resources  disk, RAM, CPU (VM gereksinimi: 250 GB boş disk, 16 GB RAM, 4 vCPU)
  tests      unit testler ve `pip check` (VM kabul kriteri)

Sonuç: ekranda tablo + outputs/<run_id>/environment_check.json (audit). Çıkış kodu: FAIL varsa 1.
Hasta verisi okunmaz; IRIS'e yalnızca `SELECT 1` ve sütun yoklaması (`WHERE 1=0`) gider; şifre yazdırılmaz.
Bu dosya yalnızca standart kütüphaneyle başlar: pandas eksik olsa da çalışır ve bunu raporlar.
"""
from __future__ import annotations

import argparse
import glob
import importlib
import importlib.util
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

MIN_PYTHON = (3, 10)
MIN_DISK_GB, MIN_RAM_GB, MIN_CPUS = 250, 16, 4          # VM gereksinimi (R9)
REQUIREMENTS = REPO_ROOT / "requirements.txt"                 # proje (FAIL)
EXPLORE_REQUIREMENTS = REPO_ROOT / "requirements-explore.txt"  # keşif, VM gereksinimi R5 (WARN); kod kullanmaz
IMPORT_NAME = {"scikit-learn": "sklearn"}
NO_IMPORT = {"intersystems-irispython"}          # sürücü yalnız io/iris.py'de yüklenir → [iris] grubunda denenir

PASS, WARN, FAIL, SKIP, INFO = "PASS", "WARN", "FAIL", "SKIP", "INFO"


@dataclass
class Result:
    group: str
    check: str
    status: str
    detail: str = ""


# --------------------------------------------------------------------------
# Yardımcılar
# --------------------------------------------------------------------------
def _version_tuple(v: str) -> tuple[int, ...]:
    """'2.1.4' → (2, 1, 4); '2.0.0rc1' → (2, 0, 0); sayısal olmayan kısımlar atılır."""
    out = []
    for part in v.split("."):
        m = re.match(r"\d+", part)
        if not m:
            break
        out.append(int(m.group()))
    return tuple(out)


def version_ok(version: str, spec: str) -> bool:
    """Basit PEP 440 alt kümesi: '>=2.0,<4', '==1.2', '>1', '<=3'. Boş spec = her sürüm."""
    v = _version_tuple(version)
    for cond in filter(None, (c.strip() for c in spec.split(","))):
        m = re.match(r"(>=|<=|==|!=|>|<)\s*(.+)", cond)
        if not m:
            raise ValueError(f"desteklenmeyen sürüm koşulu: {cond}")
        op, ref = m.group(1), _version_tuple(m.group(2))
        n = max(len(v), len(ref))
        a, b = v + (0,) * (n - len(v)), ref + (0,) * (n - len(ref))
        if not {">=": a >= b, "<=": a <= b, "==": a == b, "!=": a != b, ">": a > b, "<": a < b}[op]:
            return False
    return True


def parse_requirements(path: Path) -> list[tuple[str, str]]:
    """requirements.txt → [(dağıtım, sürüm koşulu)]; yorum ve boş satırlar atlanır."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"([A-Za-z0-9_.\-]+)\s*(.*)", line)
        out.append((m.group(1), m.group(2).strip()))
    return out


def _dist_version(dist: str) -> str | None:
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return None


def _run(cmd: list[str], timeout: float = 30, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def _gb(n_bytes: float) -> float:
    return n_bytes / 2**30


def install_hint() -> str:
    """Eksik paketleri BU Python'a kurma komutu (proje kendi venv'ini kurmaz; VM'de DHA bir kez kurar)."""
    return f"{sys.executable} -m pip install -r requirements.txt -r requirements-explore.txt"


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def dependency_closure(roots: list[str]) -> set[str]:
    """Kök paketler + kurulu metadata'ya göre tüm alt bağımlılıkları (ad, normalize). 'extra' ile gelen
    isteğe bağlı ekler atlanır; ortam işaretli (python_version …) olanlar ihtiyaten dahil edilir."""
    seen: set[str] = set()
    stack = [_norm(x) for x in roots]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        try:
            reqs = metadata.requires(n) or []
        except metadata.PackageNotFoundError:
            continue
        for req in reqs:
            if re.search(r"extra\s*==", req):
                continue
            m = re.match(r"[A-Za-z0-9_.\-]+", req)
            if m:
                stack.append(_norm(m.group()))
    return seen


def project_dependencies() -> set[str]:
    """requirements.txt + IRIS sürücüleri (io/iris.py) ve hepsinin alt bağımlılıkları."""
    roots = [d for d, _ in parse_requirements(REPO_ROOT / "requirements.txt")] + ["intersystems-irispython", "pyodbc"]
    return dependency_closure(roots)


def split_pip_check(lines: list[str], project: set[str]) -> tuple[list[str], list[str]]:
    """pip check satırları → (projenin bağımlılığına dokunanlar, diğerleri).
    Biçimler: 'A 1.0 has requirement B<2, but you have B 3.0.' · 'A 1.0 requires B, which is not installed.'"""
    ours, other = [], []
    for ln in lines:
        names = [ln.split()[0]] if ln.split() else []
        m = re.search(r"(?:has requirement|requires)\s+([A-Za-z0-9_.\-]+)", ln)
        if m:
            names.append(m.group(1))
        (ours if any(_norm(n) in project for n in names) else other).append(ln)
    return ours, other


# --------------------------------------------------------------------------
# Kontroller
# --------------------------------------------------------------------------
def check_python() -> list[Result]:
    g, r = "python", []
    v = sys.version_info
    r.append(Result(g, "Python sürümü", PASS if v[:2] >= MIN_PYTHON else FAIL,
                    f"{platform.python_version()} ({sys.executable}); gerekli ≥ {'.'.join(map(str, MIN_PYTHON))}"))
    kind = "sanal ortam" if sys.prefix != sys.base_prefix else "sistem / kullanıcı Python'u"
    r.append(Result(g, "Python ortamı", INFO, f"{sys.prefix} ({kind}) — paketler bu Python'da aranır"))
    pip_v = _dist_version("pip")
    r.append(Result(g, "pip", PASS if pip_v else FAIL, pip_v or "pip yok (python -m pip çalışmaz)"))
    has_venv = importlib.util.find_spec("venv") is not None and importlib.util.find_spec("ensurepip") is not None
    r.append(Result(g, "venv + ensurepip", PASS if has_venv else WARN,
                    "" if has_venv else "venv oluşturulamaz (Ubuntu: python3-venv)"))
    header = Path(sysconfig.get_paths()["include"]) / "Python.h"
    r.append(Result(g, "Python başlık dosyaları", PASS if header.exists() else WARN,
                    str(header) if header.exists() else "Python.h yok (Ubuntu: python3-dev)"))
    cc = shutil.which("gcc") or shutil.which("cc")
    mk = shutil.which("make")
    r.append(Result(g, "Derleyici (gcc / make)", PASS if cc and mk else WARN,
                    f"{cc}, {mk}" if cc and mk else "derleyici yok (Ubuntu: build-essential)"))
    return r


def check_core() -> list[Result]:
    g, r = "core", []
    for dist, spec in parse_requirements(REQUIREMENTS):
        v = _dist_version(dist)
        if v is None:
            r.append(Result(g, dist, FAIL, f"kurulu değil (gerekli {spec or 'herhangi bir sürüm'})"))
            continue
        if not version_ok(v, spec):
            r.append(Result(g, dist, FAIL, f"{v} kurulu, gerekli {spec}"))
            continue
        if dist in NO_IMPORT:
            r.append(Result(g, dist, PASS, f"{v} ({spec}); bağlantısı [iris] grubunda denenir"))
            continue
        try:
            importlib.import_module(IMPORT_NAME.get(dist, dist))
            r.append(Result(g, dist, PASS, f"{v} ({spec})"))
        except Exception as e:                                   # kurulu ama bozuk (ör. eksik .so)
            r.append(Result(g, dist, FAIL, f"{v} kurulu ama import edilemiyor: {type(e).__name__}: {e}"))
    try:
        importlib.import_module("sandbox.io.adapters.nabidh")
        importlib.import_module("sandbox.scores.qdiabetes2018a")
        r.append(Result(g, "Proje modülleri (src/sandbox)", PASS, "adapter ve skorlayıcılar import ediliyor"))
    except Exception as e:
        r.append(Result(g, "Proje modülleri (src/sandbox)", FAIL, f"{type(e).__name__}: {e}"))
    return r


def check_repo(github: bool) -> list[Result]:
    g, r = "repo", []
    git = shutil.which("git")
    if not git:
        r.append(Result(g, "git", WARN, "git yok: audit commit kaydı düşer, repo çekilemez"))
    else:
        r.append(Result(g, "git", PASS, _run(["git", "--version"]).stdout.strip()))
        head = _run(["git", "rev-parse", "--short", "HEAD"])
        if head.returncode != 0:
            r.append(Result(g, "Git çalışma kopyası", WARN, "bu klasör bir git deposu değil (audit commit'i yazılmaz)"))
        else:
            branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
            dirty = _run(["git", "status", "--porcelain", "--", "src", "notebooks", "tools"]).stdout.strip()
            r.append(Result(g, "Git çalışma kopyası", WARN if dirty else PASS,
                            f"{branch} @ {head.stdout.strip()}"
                            + ("; src/notebooks/tools'ta commit'lenmemiş değişiklik var (audit 'dirty' yazar)"
                               if dirty else "")))
            origin = _run(["git", "remote", "get-url", "origin"])
            url = re.sub(r"//[^@/]+@", "//", origin.stdout.strip())       # URL'deki token yazdırılmasın
            r.append(Result(g, "origin", INFO if origin.returncode == 0 else WARN, url or "origin tanımlı değil"))
            if github:
                try:
                    ls = _run(["git", "ls-remote", "--exit-code", "origin", "HEAD"], timeout=30)
                    ok = ls.returncode == 0
                    r.append(Result(g, "GitHub erişimi (git ls-remote)", PASS if ok else FAIL,
                                    "origin'e ulaşıldı" if ok else (ls.stderr.strip().splitlines() or ["hata"])[-1]))
                except subprocess.TimeoutExpired:
                    r.append(Result(g, "GitHub erişimi (git ls-remote)", FAIL, "30 sn'de yanıt yok"))
    for d in ("data", "outputs"):
        p = REPO_ROOT / d
        try:
            p.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=p, prefix=".envcheck_"):
                pass
            r.append(Result(g, f"{d}/ yazılabilir", PASS, str(p)))
        except OSError as e:
            r.append(Result(g, f"{d}/ yazılabilir", FAIL, f"{p}: {e}"))
    return r


def check_iris(required: bool, sqlite_dir: Path | None, cohorts: list[str] | None) -> tuple[list[Result], object]:
    """→ (sonuçlar, açık bağlantı ya da None). Bağlantıyı çağıran kapatır."""
    g, r = "iris", []
    try:
        from sandbox.io import iris
        from sandbox.io.adapters import nabidh
    except Exception as e:
        r.append(Result(g, "io/iris.py", FAIL, f"import edilemiyor (core paketler?): {type(e).__name__}: {e}"))
        return r, None

    if sqlite_dir:
        sq = sqlite_dir.resolve()
        cs = cohorts or [c for c in nabidh.IRIS_COHORTS if (sq / f"{c}.sqlite").is_file()]
        try:
            conn = iris.sqlite_standin({nabidh.IRIS_COHORTS[c]["schema"]: sq / f"{c}.sqlite" for c in cs})
            r.append(Result(g, "Bağlantı", PASS, f"SQLite stand-in (prova): {sq}, kohortlar {cs}"))
            return r, conn
        except Exception as e:
            r.append(Result(g, "Bağlantı", FAIL, f"SQLite stand-in açılamadı: {e}"))
            return r, None

    # 1. Sürücü — bağlantı ayarı varsa IRIS kullanılacak demektir: sürücü yoksa FAIL
    try:
        iris.connection_settings()
        configured = True
    except Exception:
        configured = False
    drivers = {d["name"]: d for d in iris.driver_status()}
    main, alt = drivers["intersystems-irispython"], drivers["pyodbc"]
    missing = FAIL if required or configured else WARN
    r.append(Result(g, "Sürücü: intersystems-irispython",
                    (WARN if main["conflict"] else PASS) if main["ok"] else (WARN if alt["ok"] else missing),
                    f"{main['version'] or ''} {main['detail']}".strip() if main["ok"] else main["detail"]))
    r.append(Result(g, "Yedek sürücü: pyodbc + IRIS ODBC", PASS if alt["ok"] else INFO,
                    f"{alt['version']}; {alt['detail']}" if alt["version"] else alt["detail"]))

    # 2. Bağlantı ayarları (şifre yazdırılmaz)
    cred = iris.credentials_file_path()
    try:
        s = iris.connection_settings()
    except Exception as e:
        r.append(Result(g, "Bağlantı ayarları", FAIL if required else SKIP,
                        f"{e}" if required else f"ayar yok → IRIS kontrolleri atlandı ({cred})"))
        return r, None
    r.append(Result(g, "Bağlantı ayarları", PASS, f"{s['target']} · kullanıcı {s['user']} · {s['driver']}"))
    if cred.is_file():
        if cred.resolve().is_relative_to(REPO_ROOT):
            r.append(Result(g, "Kimlik dosyası", FAIL, f"{cred} repo içinde — dışarı taşı (git'e girebilir)"))
        elif os.name == "posix" and cred.stat().st_mode & 0o077:
            r.append(Result(g, "Kimlik dosyası", WARN, f"{cred} başkalarınca okunabilir → chmod 600"))
        else:
            r.append(Result(g, "Kimlik dosyası", PASS, f"{cred} (yalnız sahibi okuyabilir)"))
    has_pw = bool(os.environ.get(iris.ENV_PASSWORD) or iris.read_credentials_file().get(iris.ENV_PASSWORD))
    if s["driver"] != "pyodbc" and not has_pw:
        prompt = iris.can_prompt()
        r.append(Result(g, "Şifre", WARN if prompt else FAIL,
                        "ayarlı değil — bağlanırken sorulacak" if prompt
                        else f"ayarlı değil ve sorulamıyor (terminal yok; IntelliJ'de run configuration → "
                             f"'Emulate terminal'): {iris.ENV_PASSWORD} ya da {cred}"))

    # 3. Ağ (TCP) — yalnız JDBC dizesiyle
    if s["driver"] != "pyodbc":
        t = iris.parse_url(s["_url"])
        try:
            ms = iris.tcp_check(t.host, t.port)
            r.append(Result(g, "TCP erişimi", PASS, f"{t.host}:{t.port} açık ({ms:.0f} ms)"))
        except OSError as e:
            r.append(Result(g, "TCP erişimi", FAIL, f"{t.host}:{t.port} erişilemiyor: {e} (firewall / DNS?)"))
            return r, None

    # 4. Bağlantı + SELECT 1
    try:
        conn = iris.connect()
    except Exception as e:
        r.append(Result(g, "Bağlantı (giriş)", FAIL, f"{type(e).__name__}: {str(e)[:300]}"))
        return r, None
    try:
        cur = conn.cursor()
        cur.execute(iris.assert_select("SELECT 1"))
        cur.fetchall()
        cur.close()
        r.append(Result(g, "Bağlantı + SELECT 1", PASS, s["target"]))
    except Exception as e:
        r.append(Result(g, "Bağlantı + SELECT 1", FAIL, f"{type(e).__name__}: {str(e)[:300]}"))
        conn.close()
        return r, None
    return r, conn


def check_mapping(conn, cohorts: list[str] | None) -> list[Result]:
    """SOURCES'taki her kaynağın IRIS tablosu / sorgusu ve sütunları var mı (WHERE 1=0, satır okunmaz)."""
    from sandbox.io import iris
    from sandbox.io.adapters import nabidh

    g, r = "mapping", []
    for c in cohorts or list(nabidh.IRIS_COHORTS):
        params = {"cohort": c, **nabidh.IRIS_COHORTS.get(c, {})}
        for name, spec in nabidh.SOURCES.items():
            label = f"{c} · {name}"
            try:
                src = (f"({spec['query'].format(**params)}) q" if spec.get("query")
                       else spec["table"].format(**params))
            except KeyError as e:
                r.append(Result(g, label, WARN, f"yer tutucu {e} IRIS_COHORTS['{c}']'de yok"))
                continue
            try:
                have = iris.column_names(conn, src)
            except Exception as e:
                status = INFO if spec.get("optional") else WARN
                note = "opsiyonel, ingest atlar" if spec.get("optional") else "ingest çalışmaz"
                r.append(Result(g, label, status, f"{src}: okunamadı ({type(e).__name__}: {str(e)[:150]}) — {note}"))
                continue
            low = {h.lower() for h in have}
            req = [x for x in spec["columns"].values() if x.lower() not in low]
            opt = [x for x in [*spec.get("optional_columns", {}).values(), *(spec.get("filter") or {})]
                   if x.lower() not in low]
            if req:
                r.append(Result(g, label, WARN, f"{src}: zorunlu sütun yok {req} — ingest çalışmaz. "
                                                f"Tablodaki sütunlar: {have[:25]}"))
            else:
                r.append(Result(g, label, PASS, f"{src}: {len(have)} sütun"
                                                + (f"; opsiyonel olup olmayan: {opt}" if opt else "")))
    return r


def check_explore() -> list[Result]:
    r = []
    for dist, _ in parse_requirements(EXPLORE_REQUIREMENTS):
        v = _dist_version(dist)
        r.append(Result("explore", dist, PASS if v else WARN, v or "kurulu değil"))
    return r


def check_desktop() -> list[Result]:
    g, r = "desktop", []
    linux = sys.platform.startswith("linux")
    miss = WARN if linux else INFO
    session = os.environ.get("XDG_SESSION_TYPE") or ("x11" if os.environ.get("DISPLAY") else None) \
        or ("wayland" if os.environ.get("WAYLAND_DISPLAY") else None)
    r.append(Result(g, "Masaüstü oturumu", PASS if session else miss,
                    session or ("grafik oturum yok (SSH / CLI?)" if linux else f"{sys.platform}: kontrol edilmedi")))
    idea = (shutil.which("idea") or shutil.which("idea.sh") or shutil.which("intellij-idea-ultimate")
            or next(iter(glob.glob("/opt/*idea*/bin/idea.sh") + glob.glob("/snap/bin/intellij-idea*")
                         + glob.glob(os.path.expanduser("~/.local/share/JetBrains/Toolbox/apps/*idea*"))
                         + glob.glob("/Applications/IntelliJ IDEA*.app")), None))
    r.append(Result(g, "IntelliJ IDEA", PASS if idea else miss, idea or "bulunamadı (PATH, /opt, snap, Toolbox)"))
    browser = next((b for b in ("firefox", "google-chrome", "chromium", "chromium-browser") if shutil.which(b)), None)
    r.append(Result(g, "Tarayıcı (JupyterLab / HTML raporlar)", PASS if browser else miss,
                    shutil.which(browser) if browser else "firefox / chrome bulunamadı"))
    return r


def check_resources() -> list[Result]:
    g, r = "resources", []
    du = shutil.disk_usage(REPO_ROOT)
    r.append(Result(g, "Boş disk", PASS if _gb(du.free) >= MIN_DISK_GB else WARN,
                    f"{_gb(du.free):.0f} GB boş / {_gb(du.total):.0f} GB ({REPO_ROOT}); istenen ≥ {MIN_DISK_GB} GB"))
    try:
        ram = _gb(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
        r.append(Result(g, "RAM", PASS if ram >= MIN_RAM_GB - 0.5 else WARN, f"{ram:.1f} GB; istenen ≥ {MIN_RAM_GB} GB"))
    except (ValueError, OSError, AttributeError):
        r.append(Result(g, "RAM", INFO, "ölçülemedi"))
    n = os.cpu_count() or 0
    r.append(Result(g, "CPU", PASS if n >= MIN_CPUS else WARN, f"{n} çekirdek; istenen ≥ {MIN_CPUS}"))
    return r


def check_tests() -> list[Result]:
    g, r = "tests", []
    try:
        t = _run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], timeout=900)
        lines = (t.stderr + t.stdout).splitlines()
        tail = [ln for ln in lines if ln.startswith(("Ran ", "OK", "FAILED"))]
        failed = [ln.split(":", 1)[1].strip().split(" ")[0] for ln in lines if ln.startswith(("FAIL:", "ERROR:"))]
        detail = " · ".join(tail) or t.stderr[-300:]
        if failed:
            detail += " — " + ", ".join(failed[:5]) + (f" (+{len(failed) - 5})" if len(failed) > 5 else "")
        r.append(Result(g, "Unit testler", PASS if t.returncode == 0 else FAIL, detail))
    except subprocess.TimeoutExpired:
        r.append(Result(g, "Unit testler", FAIL, "15 dk'da bitmedi"))

    p = _run([sys.executable, "-m", "pip", "check"], timeout=120)
    out = [ln for ln in (p.stdout + p.stderr).strip().splitlines() if ln.strip()]
    if p.returncode == 0:
        r.append(Result(g, "pip check", PASS, out[0] if out else "sorun yok"))
    elif _dist_version("pip") is None or not out:
        r.append(Result(g, "pip check", FAIL, "pip yok" if _dist_version("pip") is None else "çıktısız başarısız"))
    else:
        ours, other = split_pip_check(out, project_dependencies())
        if ours:
            r.append(Result(g, "pip check", FAIL, "projenin bağımlılıklarında uyumsuzluk: " + " | ".join(ours[:5])))
        if other:
            r.append(Result(g, "pip check (diğer paketler)", WARN,
                            f"{len(other)} uyumsuzluk, hiçbiri projenin bağımlılığı değil (VM kabulü temiz pip check "
                            f"ister): " + " | ".join(other[:3])))
    return r


def run_checks(*, iris_required: bool = False, iris_sqlite: Path | None = None, cohorts: list[str] | None = None,
               github: bool = False, quick: bool = False) -> list[Result]:
    results = check_python() + check_core() + check_repo(github)
    iris_results, conn = check_iris(iris_required, iris_sqlite, cohorts)
    results += iris_results
    if conn is not None:
        try:
            results += check_mapping(conn, cohorts)
        finally:
            conn.close()
    else:
        results.append(Result("mapping", "Adapter eşlemesi (IRIS)", SKIP, "IRIS bağlantısı yok"))
    results += check_explore() + check_desktop() + check_resources()
    if quick:
        results.append(Result("tests", "Unit testler + pip check", SKIP, "--quick"))
    else:
        results += check_tests()
    return results


# --------------------------------------------------------------------------
# Rapor
# --------------------------------------------------------------------------
def print_report(results: list[Result]) -> None:
    w = max(len(x.check) for x in results)
    group = None
    for x in results:
        if x.group != group:
            group = x.group
            print(f"\n[{group}]")
        print(f"  {x.status:4s}  {x.check:{w}s}  {x.detail}")
    counts = {s: sum(x.status == s for x in results) for s in (PASS, WARN, FAIL, SKIP, INFO)}
    print("\n" + " · ".join(f"{k} {v}" for k, v in counts.items() if v))
    fails = [x for x in results if x.status == FAIL]
    if fails:
        print("Ortam hazır DEĞİL — FAIL olanlar: " + "; ".join(f"{x.group}/{x.check}" for x in fails))
        if any(x.group == "core" and x.status == FAIL for x in fails):
            print(f"Paketler bu Python'da ({sys.executable}) eksik. Ya bu Python'a kur:\n  {install_hint()}\n"
                  f"ya da paketlerin kurulu olduğu Python'la çalıştır (IntelliJ: proje SDK'sı).")
    else:
        print("Ortam hazır (FAIL yok)." + (" WARN'lara bak." if counts[WARN] else ""))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Proje ortamı kontrolü (enclave VM / yerel)")
    ap.add_argument("--iris", action="store_true", help="IRIS zorunlu: ayar / sürücü / bağlantı yoksa FAIL")
    ap.add_argument("--iris-sqlite", type=Path, default=None, help="IRIS yerine <dizin>/<kohort>.sqlite (prova)")
    ap.add_argument("--cohorts", nargs="+", default=None, help="eşleme kontrolü için kohortlar (varsayılan: hepsi)")
    ap.add_argument("--github", action="store_true", help="GitHub erişimini dene (git ls-remote origin)")
    ap.add_argument("--quick", action="store_true", help="unit testleri ve pip check'i atla")
    a = ap.parse_args(argv)

    results = run_checks(iris_required=a.iris, iris_sqlite=a.iris_sqlite, cohorts=a.cohorts,
                         github=a.github, quick=a.quick)
    print_report(results)
    n_fail = sum(x.status == FAIL for x in results)

    try:                                           # audit (outputs/ yazılamıyorsa yukarıda FAIL görünür)
        from sandbox.audit import Run
        run = Run("check_environment", source=None)
        run.log("environment checked", **{s: sum(x.status == s for x in results) for s in (PASS, WARN, FAIL)})
        run.save_json({"python": sys.version, "platform": platform.platform(), "args": vars(a),
                       "results": [asdict(x) for x in results]},
                      "environment_check.json", "ortam kontrolü sonuçları")
        run.finish("success" if n_fail == 0 else "checks_failed")
        print(f"Run: {run.run_id} → outputs/{run.run_id}/environment_check.json")
    except Exception as e:
        print(f"Audit yazılamadı: {type(e).__name__}: {e}")
        n_fail += 1
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
