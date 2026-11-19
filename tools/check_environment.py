"""Environment check: does this machine (the enclave VM or a local one) have everything the project needs to run?

Usage:
  python tools/check_environment.py                   # everything; IRIS too if IRIS connection settings exist
  python tools/check_environment.py --iris            # IRIS required: FAIL without settings / driver / connection
  python tools/check_environment.py --iris-sqlite data/nabidh_dryrun/iris     # SQLite instead of IRIS (dry run)
  python tools/check_environment.py --github          # GitHub access (git ls-remote origin)
  python tools/check_environment.py --quick           # skip the unit tests and pip check

Groups (FAIL = the project cannot run here; WARN = missing but not blocking):
  python     Python ≥ 3.10, pip, venv, header files and compiler (python3-dev, build-essential)
  core       requirements.txt packages installed, within version range and importable (IRIS driver included)
  repo       git, commit, working tree; data/ and outputs/ writable
  iris       driver (intersystems-irispython; fallback pyodbc), connection settings, TCP, connection + SELECT 1
  mapping    do the adapter SOURCES / IRIS_COHORTS tables and columns exist in IRIS (no rows read).
             Gaps are WARN: not an environment problem but a mapping to fix in nabidh.py — ingest fails as it is, though
  explore    requirements-explore.txt: exploration packages (Jupyter, scipy, polars …) — not project dependencies
  desktop    desktop session, IntelliJ, browser (WARN on Linux only)
  resources  disk, RAM, CPU (VM requirement: 250 GB free disk, 16 GB RAM, 4 vCPU)
  tests      unit tests and `pip check` (VM acceptance criterion)

Result: a table on screen + outputs/<run_id>/environment_check.json (audit). Exit code: 1 if any FAIL.
No patient data is read; only `SELECT 1` and a column probe (`WHERE 1=0`) go to IRIS; the password is never printed.
This file starts with the standard library only: it runs even without pandas and reports that.
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
MIN_DISK_GB, MIN_RAM_GB, MIN_CPUS = 250, 16, 4          # VM requirement (R9)
REQUIREMENTS = REPO_ROOT / "requirements.txt"                 # project (FAIL)
EXPLORE_REQUIREMENTS = REPO_ROOT / "requirements-explore.txt"  # exploration, VM requirement R5 (WARN); code does not use it
IMPORT_NAME = {"scikit-learn": "sklearn"}
NO_IMPORT = {"intersystems-irispython"}          # the driver loads only in io/iris.py → tried in the [iris] group

PASS, WARN, FAIL, SKIP, INFO = "PASS", "WARN", "FAIL", "SKIP", "INFO"


@dataclass
class Result:
    group: str
    check: str
    status: str
    detail: str = ""


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _version_tuple(v: str) -> tuple[int, ...]:
    """'2.1.4' → (2, 1, 4); '2.0.0rc1' → (2, 0, 0); non-numeric parts are dropped."""
    out = []
    for part in v.split("."):
        m = re.match(r"\d+", part)
        if not m:
            break
        out.append(int(m.group()))
    return tuple(out)


def version_ok(version: str, spec: str) -> bool:
    """Simple PEP 440 subset: '>=2.0,<4', '==1.2', '>1', '<=3'. Empty spec = any version."""
    v = _version_tuple(version)
    for cond in filter(None, (c.strip() for c in spec.split(","))):
        m = re.match(r"(>=|<=|==|!=|>|<)\s*(.+)", cond)
        if not m:
            raise ValueError(f"unsupported version condition: {cond}")
        op, ref = m.group(1), _version_tuple(m.group(2))
        n = max(len(v), len(ref))
        a, b = v + (0,) * (n - len(v)), ref + (0,) * (n - len(ref))
        if not {">=": a >= b, "<=": a <= b, "==": a == b, "!=": a != b, ">": a > b, "<": a < b}[op]:
            return False
    return True


def parse_requirements(path: Path) -> list[tuple[str, str]]:
    """requirements.txt → [(distribution, version condition)]; comments and blank lines are skipped."""
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
    """Command that installs the missing packages into THIS Python (the project sets up no venv; on the VM DHA
    installs once)."""
    return f"{sys.executable} -m pip install -r requirements.txt -r requirements-explore.txt"


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def dependency_closure(roots: list[str]) -> set[str]:
    """Root packages + all their transitive dependencies from the installed metadata (normalised names). Optional
    'extra' additions are skipped; ones with environment markers (python_version …) are included to be safe."""
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
    """requirements.txt + the IRIS drivers (io/iris.py) and all their transitive dependencies."""
    roots = [d for d, _ in parse_requirements(REPO_ROOT / "requirements.txt")] + ["intersystems-irispython", "pyodbc"]
    return dependency_closure(roots)


def split_pip_check(lines: list[str], project: set[str]) -> tuple[list[str], list[str]]:
    """pip check lines → (those touching a project dependency, the rest).
    Formats: 'A 1.0 has requirement B<2, but you have B 3.0.' · 'A 1.0 requires B, which is not installed.'"""
    ours, other = [], []
    for ln in lines:
        names = [ln.split()[0]] if ln.split() else []
        m = re.search(r"(?:has requirement|requires)\s+([A-Za-z0-9_.\-]+)", ln)
        if m:
            names.append(m.group(1))
        (ours if any(_norm(n) in project for n in names) else other).append(ln)
    return ours, other


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------
def check_python() -> list[Result]:
    g, r = "python", []
    v = sys.version_info
    r.append(Result(g, "Python version", PASS if v[:2] >= MIN_PYTHON else FAIL,
                    f"{platform.python_version()} ({sys.executable}); required ≥ {'.'.join(map(str, MIN_PYTHON))}"))
    kind = "virtual environment" if sys.prefix != sys.base_prefix else "system / user Python"
    r.append(Result(g, "Python environment", INFO, f"{sys.prefix} ({kind}) — packages are looked up in this Python"))
    pip_v = _dist_version("pip")
    r.append(Result(g, "pip", PASS if pip_v else FAIL, pip_v or "no pip (python -m pip does not work)"))
    has_venv = importlib.util.find_spec("venv") is not None and importlib.util.find_spec("ensurepip") is not None
    r.append(Result(g, "venv + ensurepip", PASS if has_venv else WARN,
                    "" if has_venv else "cannot create a venv (Ubuntu: python3-venv)"))
    header = Path(sysconfig.get_paths()["include"]) / "Python.h"
    r.append(Result(g, "Python header files", PASS if header.exists() else WARN,
                    str(header) if header.exists() else "no Python.h (Ubuntu: python3-dev)"))
    cc = shutil.which("gcc") or shutil.which("cc")
    mk = shutil.which("make")
    r.append(Result(g, "Compiler (gcc / make)", PASS if cc and mk else WARN,
                    f"{cc}, {mk}" if cc and mk else "no compiler (Ubuntu: build-essential)"))
    return r


def check_core() -> list[Result]:
    g, r = "core", []
    for dist, spec in parse_requirements(REQUIREMENTS):
        v = _dist_version(dist)
        if v is None:
            r.append(Result(g, dist, FAIL, f"not installed (required {spec or 'any version'})"))
            continue
        if not version_ok(v, spec):
            r.append(Result(g, dist, FAIL, f"{v} installed, required {spec}"))
            continue
        if dist in NO_IMPORT:
            r.append(Result(g, dist, PASS, f"{v} ({spec}); its connection is tried in the [iris] group"))
            continue
        try:
            importlib.import_module(IMPORT_NAME.get(dist, dist))
            r.append(Result(g, dist, PASS, f"{v} ({spec})"))
        except Exception as e:                                   # installed but broken (e.g. a missing .so)
            r.append(Result(g, dist, FAIL, f"{v} installed but cannot be imported: {type(e).__name__}: {e}"))
    try:
        importlib.import_module("sandbox.io.adapters.nabidh")
        importlib.import_module("sandbox.scores.qdiabetes2018a")
        r.append(Result(g, "Project modules (src/sandbox)", PASS, "adapter and scorers import"))
    except Exception as e:
        r.append(Result(g, "Project modules (src/sandbox)", FAIL, f"{type(e).__name__}: {e}"))
    return r


def check_repo(github: bool) -> list[Result]:
    g, r = "repo", []
    git = shutil.which("git")
    if not git:
        r.append(Result(g, "git", WARN, "no git: the audit loses the commit record, the repo cannot be pulled"))
    else:
        r.append(Result(g, "git", PASS, _run(["git", "--version"]).stdout.strip()))
        head = _run(["git", "rev-parse", "--short", "HEAD"])
        if head.returncode != 0:
            r.append(Result(g, "Git working copy", WARN, "this folder is not a git repository (audit records no commit)"))
        else:
            branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
            dirty = _run(["git", "status", "--porcelain", "--", "src", "notebooks", "tools"]).stdout.strip()
            r.append(Result(g, "Git working copy", WARN if dirty else PASS,
                            f"{branch} @ {head.stdout.strip()}"
                            + ("; uncommitted changes in src/notebooks/tools (audit records 'dirty')"
                               if dirty else "")))
            origin = _run(["git", "remote", "get-url", "origin"])
            url = re.sub(r"//[^@/]+@", "//", origin.stdout.strip())       # never print a token in the URL
            r.append(Result(g, "origin", INFO if origin.returncode == 0 else WARN, url or "origin not set"))
            if github:
                try:
                    ls = _run(["git", "ls-remote", "--exit-code", "origin", "HEAD"], timeout=30)
                    ok = ls.returncode == 0
                    r.append(Result(g, "GitHub access (git ls-remote)", PASS if ok else FAIL,
                                    "origin reached" if ok else (ls.stderr.strip().splitlines() or ["error"])[-1]))
                except subprocess.TimeoutExpired:
                    r.append(Result(g, "GitHub access (git ls-remote)", FAIL, "no answer within 30 s"))
    for d in ("data", "outputs"):
        p = REPO_ROOT / d
        try:
            p.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=p, prefix=".envcheck_"):
                pass
            r.append(Result(g, f"{d}/ writable", PASS, str(p)))
        except OSError as e:
            r.append(Result(g, f"{d}/ writable", FAIL, f"{p}: {e}"))
    return r + check_env_file()


def check_env_file() -> list[Result]:
    """The untracked `.env` (src/sandbox/envfile.py): only key names are printed, never values."""
    g = "repo"
    try:
        from sandbox import envfile
        p = envfile.path()
        keys = sorted(envfile.parse(p.read_text(encoding="utf-8"))) if p and p.is_file() else None
    except Exception as e:
        return [Result(g, ".env", WARN, f"unreadable: {type(e).__name__}")]
    if keys is None:
        return [Result(g, ".env", INFO, "none (optional; instead of export: SANDBOX_SOURCE, NABIDH_IRIS_PASSWORD)")]
    r = [Result(g, ".env", INFO, f"{p.name}: {', '.join(keys) or 'no keys'} (values not printed; an environment "
                                 "variable overrides .env)")]
    if shutil.which("git") and p.resolve().is_relative_to(REPO_ROOT):
        ignored = _run(["git", "check-ignore", "-q", str(p)]).returncode == 0
        if not ignored:
            r.append(Result(g, ".env ignored by git", WARN, "not in .gitignore — the password could be committed"))
    return r


def check_iris(required: bool, sqlite_dir: Path | None, cohorts: list[str] | None) -> tuple[list[Result], object]:
    """→ (results, open connection or None). The caller closes the connection."""
    g, r = "iris", []
    try:
        from sandbox.io import iris
        from sandbox.io.adapters import nabidh
    except Exception as e:
        r.append(Result(g, "io/iris.py", FAIL, f"cannot be imported (core packages?): {type(e).__name__}: {e}"))
        return r, None

    if sqlite_dir:
        sq = sqlite_dir.resolve()
        cs = cohorts or [c for c in nabidh.IRIS_COHORTS if (sq / f"{c}.sqlite").is_file()]
        try:
            conn = iris.sqlite_standin({nabidh.IRIS_COHORTS[c]["schema"]: sq / f"{c}.sqlite" for c in cs})
            r.append(Result(g, "Connection", PASS, f"SQLite stand-in (dry run): {sq}, cohorts {cs}"))
            return r, conn
        except Exception as e:
            r.append(Result(g, "Connection", FAIL, f"could not open the SQLite stand-in: {e}"))
            return r, None

    # 1. Driver — connection settings mean IRIS will be used: FAIL if there is no driver
    try:
        iris.connection_settings()
        configured = True
    except Exception:
        configured = False
    drivers = {d["name"]: d for d in iris.driver_status()}
    main, alt = drivers["intersystems-irispython"], drivers["pyodbc"]
    missing = FAIL if required or configured else WARN
    r.append(Result(g, "Driver: intersystems-irispython",
                    (WARN if main["conflict"] else PASS) if main["ok"] else (WARN if alt["ok"] else missing),
                    f"{main['version'] or ''} {main['detail']}".strip() if main["ok"] else main["detail"]))
    r.append(Result(g, "Fallback driver: pyodbc + IRIS ODBC", PASS if alt["ok"] else INFO,
                    f"{alt['version']}; {alt['detail']}" if alt["version"] else alt["detail"]))

    # 2. Connection settings (the password is never printed)
    cred = iris.credentials_file_path()
    try:
        s = iris.connection_settings()
    except Exception as e:
        r.append(Result(g, "Connection settings", FAIL if required else SKIP,
                        f"{e}" if required else f"no settings → IRIS checks skipped ({cred})"))
        return r, None
    r.append(Result(g, "Connection settings", PASS, f"{s['target']} · user {s['user']} · {s['driver']}"))
    if cred.is_file():
        if cred.resolve().is_relative_to(REPO_ROOT):
            r.append(Result(g, "Credentials file", FAIL, f"{cred} is inside the repo — move it out (it could end up in git)"))
        elif os.name == "posix" and cred.stat().st_mode & 0o077:
            r.append(Result(g, "Credentials file", WARN, f"{cred} is readable by others → chmod 600"))
        else:
            r.append(Result(g, "Credentials file", PASS, f"{cred} (readable by its owner only)"))
    has_pw = bool(os.environ.get(iris.ENV_PASSWORD) or iris.read_credentials_file().get(iris.ENV_PASSWORD))
    if s["driver"] != "pyodbc" and not has_pw:
        prompt = iris.can_prompt()
        r.append(Result(g, "Password", WARN if prompt else FAIL,
                        "not set — will be asked when connecting" if prompt
                        else f"not set and cannot be asked (no terminal; in IntelliJ: run configuration → "
                             f"'Emulate terminal'): {iris.ENV_PASSWORD} or {cred}"))

    # 3. Network (TCP) — only with a JDBC string
    if s["driver"] != "pyodbc":
        t = iris.parse_url(s["_url"])
        try:
            ms = iris.tcp_check(t.host, t.port)
            r.append(Result(g, "TCP access", PASS, f"{t.host}:{t.port} open ({ms:.0f} ms)"))
        except OSError as e:
            r.append(Result(g, "TCP access", FAIL, f"{t.host}:{t.port} unreachable: {e} (firewall / DNS?)"))
            return r, None

    # 4. Connection + SELECT 1
    try:
        conn = iris.connect()
    except Exception as e:
        r.append(Result(g, "Connection (login)", FAIL, f"{type(e).__name__}: {str(e)[:300]}"))
        return r, None
    try:
        cur = conn.cursor()
        cur.execute(iris.assert_select("SELECT 1"))
        cur.fetchall()
        cur.close()
        r.append(Result(g, "Connection + SELECT 1", PASS, s["target"]))
    except Exception as e:
        r.append(Result(g, "Connection + SELECT 1", FAIL, f"{type(e).__name__}: {str(e)[:300]}"))
        conn.close()
        return r, None
    return r, conn


def check_mapping(conn, cohorts: list[str] | None) -> list[Result]:
    """Does every SOURCES entry's IRIS table / query and its columns exist (WHERE 1=0, no rows read)."""
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
                r.append(Result(g, label, WARN, f"placeholder {e} missing from IRIS_COHORTS['{c}']"))
                continue
            try:
                have = iris.column_names(conn, src)
            except Exception as e:
                status = INFO if spec.get("optional") else WARN
                note = "optional, ingest skips it" if spec.get("optional") else "ingest will fail"
                r.append(Result(g, label, status, f"{src}: unreadable ({type(e).__name__}: {str(e)[:150]}) — {note}"))
                continue
            low = {h.lower() for h in have}
            opt_srcs = [*spec.get("optional_columns", {}).values(), *nabidh.filter_columns(spec).values()]
            req, opt = ([nabidh.label(x) for x in srcs if not any(c.lower() in low for c in nabidh.alternatives(x))]
                        for srcs in (spec["columns"].values(), opt_srcs))
            if req:
                r.append(Result(g, label, WARN, f"{src}: required columns missing {req} — ingest will fail. "
                                                f"Columns in the table: {have[:25]}"))
            else:
                r.append(Result(g, label, PASS, f"{src}: {len(have)} columns"
                                                + (f"; optional columns missing: {opt}" if opt else "")))
    return r


def check_explore() -> list[Result]:
    r = []
    for dist, _ in parse_requirements(EXPLORE_REQUIREMENTS):
        v = _dist_version(dist)
        r.append(Result("explore", dist, PASS if v else WARN, v or "not installed"))
    return r


def check_desktop() -> list[Result]:
    g, r = "desktop", []
    linux = sys.platform.startswith("linux")
    miss = WARN if linux else INFO
    session = os.environ.get("XDG_SESSION_TYPE") or ("x11" if os.environ.get("DISPLAY") else None) \
        or ("wayland" if os.environ.get("WAYLAND_DISPLAY") else None)
    r.append(Result(g, "Desktop session", PASS if session else miss,
                    session or ("no graphical session (SSH / CLI?)" if linux else f"{sys.platform}: not checked")))
    idea = (shutil.which("idea") or shutil.which("idea.sh") or shutil.which("intellij-idea-ultimate")
            or next(iter(glob.glob("/opt/*idea*/bin/idea.sh") + glob.glob("/snap/bin/intellij-idea*")
                         + glob.glob(os.path.expanduser("~/.local/share/JetBrains/Toolbox/apps/*idea*"))
                         + glob.glob("/Applications/IntelliJ IDEA*.app")), None))
    r.append(Result(g, "IntelliJ IDEA", PASS if idea else miss, idea or "not found (PATH, /opt, snap, Toolbox)"))
    browser = next((b for b in ("firefox", "google-chrome", "chromium", "chromium-browser") if shutil.which(b)), None)
    r.append(Result(g, "Browser (JupyterLab / HTML reports)", PASS if browser else miss,
                    shutil.which(browser) if browser else "firefox / chrome not found"))
    return r


def check_resources() -> list[Result]:
    g, r = "resources", []
    du = shutil.disk_usage(REPO_ROOT)
    r.append(Result(g, "Free disk", PASS if _gb(du.free) >= MIN_DISK_GB else WARN,
                    f"{_gb(du.free):.0f} GB free / {_gb(du.total):.0f} GB ({REPO_ROOT}); required ≥ {MIN_DISK_GB} GB"))
    try:
        ram = _gb(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
        r.append(Result(g, "RAM", PASS if ram >= MIN_RAM_GB - 0.5 else WARN, f"{ram:.1f} GB; required ≥ {MIN_RAM_GB} GB"))
    except (ValueError, OSError, AttributeError):
        r.append(Result(g, "RAM", INFO, "could not be measured"))
    n = os.cpu_count() or 0
    r.append(Result(g, "CPU", PASS if n >= MIN_CPUS else WARN, f"{n} cores; required ≥ {MIN_CPUS}"))
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
        r.append(Result(g, "Unit tests", PASS if t.returncode == 0 else FAIL, detail))
    except subprocess.TimeoutExpired:
        r.append(Result(g, "Unit tests", FAIL, "did not finish within 15 min"))

    p = _run([sys.executable, "-m", "pip", "check"], timeout=120)
    out = [ln for ln in (p.stdout + p.stderr).strip().splitlines() if ln.strip()]
    if p.returncode == 0:
        r.append(Result(g, "pip check", PASS, out[0] if out else "no problems"))
    elif _dist_version("pip") is None or not out:
        r.append(Result(g, "pip check", FAIL, "no pip" if _dist_version("pip") is None else "failed without output"))
    else:
        ours, other = split_pip_check(out, project_dependencies())
        if ours:
            r.append(Result(g, "pip check", FAIL, "conflicts in project dependencies: " + " | ".join(ours[:5])))
        if other:
            r.append(Result(g, "pip check (other packages)", WARN,
                            f"{len(other)} conflicts, none in a project dependency (VM acceptance asks for a clean pip "
                            f"check): " + " | ".join(other[:3])))
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
        results.append(Result("mapping", "Adapter mapping (IRIS)", SKIP, "no IRIS connection"))
    results += check_explore() + check_desktop() + check_resources()
    if quick:
        results.append(Result("tests", "Unit tests + pip check", SKIP, "--quick"))
    else:
        results += check_tests()
    return results


# --------------------------------------------------------------------------
# Report
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
        print("Environment NOT ready — FAIL: " + "; ".join(f"{x.group}/{x.check}" for x in fails))
        if any(x.group == "core" and x.status == FAIL for x in fails):
            print(f"Packages are missing in this Python ({sys.executable}). Either install them into this Python:\n"
                  f"  {install_hint()}\n"
                  f"or run with the Python that has the packages (IntelliJ: the project SDK).")
    else:
        print("Environment ready (no FAIL)." + (" Check the WARNs." if counts[WARN] else ""))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Project environment check (enclave VM / local)")
    ap.add_argument("--iris", action="store_true", help="IRIS required: FAIL without settings / driver / connection")
    ap.add_argument("--iris-sqlite", type=Path, default=None, help="<dir>/<cohort>.sqlite instead of IRIS (dry run)")
    ap.add_argument("--cohorts", nargs="+", default=None, help="cohorts for the mapping check (default: all)")
    ap.add_argument("--github", action="store_true", help="try GitHub access (git ls-remote origin)")
    ap.add_argument("--quick", action="store_true", help="skip the unit tests and pip check")
    a = ap.parse_args(argv)

    results = run_checks(iris_required=a.iris, iris_sqlite=a.iris_sqlite, cohorts=a.cohorts,
                         github=a.github, quick=a.quick)
    print_report(results)
    n_fail = sum(x.status == FAIL for x in results)

    try:                                           # audit (if outputs/ is not writable, a FAIL shows above)
        from sandbox.audit import Run
        run = Run("check_environment", source=None)
        run.log("environment checked", **{s: sum(x.status == s for x in results) for s in (PASS, WARN, FAIL)})
        run.save_json({"python": sys.version, "platform": platform.platform(), "args": vars(a),
                       "results": [asdict(x) for x in results]},
                      "environment_check.json", "environment check results")
        run.finish("success" if n_fail == 0 else "checks_failed")
        print(f"Run: {run.run_id} → outputs/{run.run_id}/environment_check.json")
    except Exception as e:
        print(f"Could not write the audit: {type(e).__name__}: {e}")
        n_fail += 1
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
