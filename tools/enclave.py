"""Enclave terminal tool: tries the VM requirements (R1–R9) one by one, sets up IRIS access, explores IRIS
(in place of the IntelliJ Database tool), checks the adapter mapping and runs the Phase 1 steps.

Run from the repo root (on the VM ~/Desktop/albert-dha/albert-dha-sandbox). Copy-paste the commands from
docs/enclave_terminal.md; tools/enclave.sh finds the project's Python:
  bash tools/enclave.sh req R5            # one requirement; several: req R7 R8; all: req all
  bash tools/enclave.sh iris-setup        # ~/.nabidh_iris (URL + user; the password is not written to the file)
  bash tools/enclave.sh schemas | tables SCHEMA | columns SCHEMA.TABLE | values SCHEMA.TABLE COLUMN
  bash tools/enclave.sh find smok | count "SELECT ..." | mapping c1 c2
  bash tools/enclave.sh run ingest|nb0|nb1|nb2|kpi
  bash tools/enclave.sh show nb1 nb01/score_summary.csv | last

Each command's result is printed between two marker lines:
  ----8<---- COPY START | <command> | [SANDBOX_PARAMS {…} |] <time> | ingest v<version> | commit <sha> | python <version> | <run_id> ----8<----
  ...
  ----8<---- COPY END ----8<----
Only this block is copied out of the enclave. The block holds metadata and summaries only: table / column names,
types, statuses, counts (< 10 → "<10"), value shapes and categorical values seen in ≥ 10 patients. No patient-level
value is printed (rules: src/sandbox/io/explore.py). The full screen output of `run` steps stays outside the block.
SANDBOX_PARAMS, when set, is in the header (parameter values only); a `run` step's "Run:" line says "params override"
for a run that differs from config.PARAMS — the KPI report does not use such runs (kpi.find_run).
Every block (header … end marker, nothing else) is also appended to logs/enclave/<UTC date>.log in the repo root,
the file carried to the repo outside the enclave; the line under the block names it. Every command is audited:
outputs/<run_id>/enclave/block.txt (+ the full output .log for run steps); `last` reprints the last block (not
appended again). Only SELECT goes to IRIS; the password is never printed or written to a file or the audit.

This file starts with the standard library only: `req` runs even without pandas and reports what is missing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import glob
import ipaddress
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
from fnmatch import fnmatch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import check_environment as ce  # noqa: E402  (standard library only)

Result, PASS, WARN, FAIL, SKIP, INFO = ce.Result, ce.PASS, ce.WARN, ce.FAIL, ce.SKIP, ce.INFO

DEFAULT_IRIS_HOST = "dhasbxnbprddb01.dha.ae"      # DHA's connection string (VM Requirements R7)
DEFAULT_IRIS_PORT = 51772
CMD = "bash tools/enclave.sh"   # from the repo root
MARK = "----8<----"
MARK_START = f"{MARK} COPY START"
MARK_END = f"{MARK} COPY END {MARK}"
# one file per UTC day, blocks in order: copied whole to the repo outside the enclave (docs/enclave_terminal.md §1)
LOG_DIR = REPO_ROOT / "logs" / "enclave"

# run steps: script, audit run name (outputs/<ts>_<name>_<hex>)
STEPS = {
    "ingest": ("tools/ingest_nabidh.py", "ingest_nabidh"),
    "nb0": ("notebooks/00_data_profile.py", "nb00_data_profile"),
    "nb1": ("notebooks/01_c1_c2_feasibility.py", "nb01_c1_c2_feasibility"),
    "nb2": ("notebooks/02_c3_benchmark.py", "nb02_c3_benchmark"),
    "kpi": ("tools/kpi_report.py", "kpi_report"),
}
# `run all`: the Phase 1 (C1 / C2) chain, one block (docs/faz1_c1_c2.md)
RUN_ALL = ("ingest", "nb0", "nb1", "kpi")
# summary tables printed into the block after a run: (file, row filter, columns)
SUMMARY_TABLES = {
    "nb0": [("nb00/schema_validation.csv", "issues", None), ("nb00/volume.csv", None, None),
            ("nb00/framework_match.csv", "framework_pivot", None),
            ("nb00/framework_variables.csv", None,
             ["cohort", "variable", "source_field", "route", "patients_with_value", "pct_patients", "status", "reason"]),
            ("nb00/unmapped_codes.csv", None, None),
            ("nb00/kpi_preview.csv", None, None)],
    "nb1": [("nb01/completeness_by_variable.csv", "group_all", None),
            ("nb01/ethnicity_source_compare.csv", "group_all", None),
            ("nb01/ethnicity_mapping_by_source.csv", None, None),
            ("nb01/score_computability.csv", None, None), ("nb01/score_missing_reasons.csv", None, None), ("nb01/smoking_source.csv", None, None),
            ("nb01/c1_detection_rate.csv", None,
             ["cohort", "reference", "group", "score", "n", "n_computable", "n_flagged", "sens_computable",
              "ci_low", "ci_high", "threshold"]),
            ("nb01/score_summary.csv", None, None), ("nb01/joint_completeness.csv", None, None)],
    "nb2": [("nb02/coverage.csv", None, None), ("nb02/performance.csv", None, None)],
    "kpi": [("kpi/kpi_table.csv", None, ["kpi", "target", "actual", "met"]),
            ("kpi/kpi_table.csv", "audit_notes", ["kpi", "notes"]),          # open run ids (no patient data)
            ("kpi/kpi_table.csv", "completeness_notes", ["kpi", "notes"])],  # weakest variable, without ethnicity
}
_COUNTISH = re.compile(r"(^n$|^np$|^n_|_n$|count|patients|^rows|_rows$|events)", re.IGNORECASE)
_NOT_COUNT = re.compile(r"(pct|percent|rate|ratio|share|sens|median|mean)", re.IGNORECASE)


# --------------------------------------------------------------------------
# Block to copy + audit
# --------------------------------------------------------------------------
class Block:
    """Output to copy out of the enclave. The header is printed on the first write (questions / step output
    before it stay out of the block); `close` prints the end marker. Lines are kept for the audit."""

    def __init__(self, header: str):
        self.header, self.lines, self.started = header, [], False

    def __call__(self, text: str = "") -> None:
        if not self.started:
            self.started = True
            self._emit(self.header)
        for ln in str(text).splitlines() or [""]:
            self._emit(ln)

    def _emit(self, ln: str) -> None:
        print(ln, flush=True)
        self.lines.append(ln)

    def table(self, df, max_rows: int = 60) -> None:
        if df is None or len(df) == 0:
            self("  (empty)")
            return
        for ln in df.head(max_rows).to_string(index=False).splitlines():
            self("  " + ln)
        if len(df) > max_rows:
            self(f"  ... +{len(df) - max_rows} more rows (raise with --max-rows)")

    def close(self) -> None:
        if not self.started:
            self("(no output)")
        self._emit(MARK_END)


def _git(*args: str) -> str:
    try:
        p = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def ingest_version() -> str:
    try:
        from sandbox.io.adapters import nabidh
        return nabidh.INGEST_VERSION
    except Exception:                              # missing package etc.: the header is still printed
        return "?"


def data_versions(source: str) -> str:
    """Which ingest the canonical data came from (ingest.json per cohort): in NB / KPI blocks."""
    from sandbox.config import CANONICAL_DIR

    parts = []
    for f in sorted((CANONICAL_DIR / source).glob("*/ingest.json")):
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
            parts.append(f"{f.parent.name} ingest v{m.get('ingest_version')} ({m.get('ingest_run_id')})")
        except (OSError, ValueError):
            parts.append(f"{f.parent.name} ingest.json unreadable")
    return "; ".join(parts) or "ingest version unknown (no ingest.json)"


def commit_label() -> str:
    """Block header: the repo's commit (+changes). A one-file bundle (tools/build_bundle.py) replaces this with the
    commit it was built from and its own id."""
    sha = _git("rev-parse", "--short", "HEAD") or "?"
    return sha + ("+changes" if _git("status", "--porcelain", "--", "src", "notebooks", "tools") else "")


def short_json(obj, limit: int = 200) -> str:
    text = json.dumps(obj, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "..."


def params_label() -> str:
    """Block header: SANDBOX_PARAMS when set — a sensitivity / exploratory run, not a decision. Parameter values only
    (no patient data). The KPI report does not use runs with an override."""
    raw = os.environ.get("SANDBOX_PARAMS", "").strip()
    if not raw:
        return ""
    try:
        val = json.loads(raw)
    except ValueError:
        text = " ".join(raw.split())
        return f"SANDBOX_PARAMS (not valid JSON) {text[:120]}{'...' if len(text) > 120 else ''}"
    return "" if val == {} else f"SANDBOX_PARAMS {short_json(val)}"


def run_line(name: str, rec: dict) -> str:
    """`run` step: one line per audit run the step made; "params override" = parameters that differ from config.PARAMS
    (exploratory: the KPI report does not use it)."""
    from sandbox.audit import recorded_override

    line = f"Run: {name} · status: {rec.get('status')} · {len(rec.get('outputs', []))} outputs"
    ov = recorded_override(rec)
    if ov:
        line += f" · params override {short_json(ov)}"
    if rec.get("override_inputs"):
        line += " · KPI inputs with params override (--allow-overrides): " + ", ".join(rec["override_inputs"])
    return line


def kpi_input_lines(d: Path) -> list[str]:
    """`run kpi`: which NB runs the KPI table used and which it left out for a parameter override (run ids only)."""
    f = d / "kpi" / "graduation.json"
    if not f.is_file():
        return []
    try:
        meta = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    skipped = meta.get("skipped_override_runs") or {}
    used = " · ".join(f"{k} {v or ('none (only runs with params override)' if k in skipped else 'none')}"
                      for k, v in (meta.get("runs") or {}).items())
    from sandbox.kpi import override_lines
    return ([f"KPI inputs: {used}"] if used else []) + override_lines(meta)


def open_run(cmd: str):
    try:
        from sandbox.audit import Run
        return Run(f"enclave_{cmd.replace('-', '_')}", source=os.environ.get("SANDBOX_SOURCE"))
    except Exception as e:                       # outputs/ not writable etc. — the block is still printed
        print(f"(could not open the audit: {type(e).__name__}: {e})")
        return None


def repo_rel(p: Path) -> str:
    try:
        return Path(p).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(p)


def day_log(when: dt.datetime) -> Path:
    return LOG_DIR / f"{when:%Y-%m-%d}.log"


def save_block(block: Block, when: dt.datetime) -> Path | None:
    """Appends the block's lines (header … end marker; screen output never enters `block.lines`) to the day's file
    and prints its path under the block. `when` = the header's time, so a run past midnight stays in its day."""
    p = day_log(when)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        gap = "\n" if p.is_file() and p.stat().st_size else ""
        with p.open("a", encoding="utf-8") as fh:
            fh.write(gap + "\n".join(block.lines) + "\n")
        n = sum(ln.startswith(MARK_START) for ln in p.read_text(encoding="utf-8").splitlines())
    except OSError as e:
        print(f"(could not save the block to {repo_rel(p)}: {type(e).__name__}: {e})")
        return None
    print(f"Saved to {repo_rel(p)} (block {n} of the UTC day)")
    return p


def finish_run(run, block: Block, rc: int, argv: list[str], saved: Path | None = None) -> None:
    if run is None:
        return
    try:
        p = run.path("enclave/block.txt")
        p.write_text("\n".join(block.lines) + "\n", encoding="utf-8")
        run.register_output(p, "COPY block printed to the terminal")
        run.log("enclave command", argv=argv, exit_code=rc, block_log=repo_rel(saved) if saved else None)
        run.finish("success" if rc == 0 else "failed")
    except Exception as e:
        print(f"(could not write the audit: {type(e).__name__}: {e})")


def safe_argv(argv: list[str]) -> list[str]:
    """Arguments for the block header / audit: whatever follows ';' / '?' in --url (driver parameters) is dropped."""
    out, cut = [], lambda u: re.split(r"[;?]", u, maxsplit=1)[0]
    for i, x in enumerate(argv):
        if x.startswith("--url="):
            x = "--url=" + cut(x[6:])
        elif i and argv[i - 1] == "--url":
            x = cut(x)
        out.append(x)
    return out


def tilde(p: Path) -> str:
    try:
        return "~/" + str(Path(p).resolve().relative_to(Path.home().resolve()))
    except ValueError:
        return str(p)


def print_results(out: Block, results: list) -> None:
    groups = list(dict.fromkeys(r.group for r in results))
    w = max((len(r.check) for r in results), default=10)
    cur = None
    for x in results:
        if len(groups) > 1 and x.group != cur:
            cur = x.group
            out(f"  [{cur}]")
        out(f"  {x.status:4s}  {x.check:{w}s}  {x.detail}")


def worst(results: list) -> str:
    st = {r.status for r in results}
    return next((s for s in (FAIL, WARN, PASS, INFO, SKIP) if s in st), SKIP)


def _cmd(cmd: list[str], timeout: float = 20):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


# --------------------------------------------------------------------------
# R1–R9: VM requirements (Data Exploration Environment – VM Requirements)
# --------------------------------------------------------------------------
def os_release() -> dict:
    out = {}
    p = Path("/etc/os-release")
    if p.is_file():
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in ln:
                k, v = ln.split("=", 1)
                out[k.strip()] = v.strip().strip('"')
    return out


def req_r1(a) -> list:
    g, r = "R1", []
    if sys.platform.startswith("linux"):
        osr = os_release()
        ok = osr.get("ID") == "ubuntu" and ce._version_tuple(osr.get("VERSION_ID", "0")) >= (22,)
        r.append(Result(g, "Operating system", PASS if ok else WARN,
                        f"{osr.get('PRETTY_NAME', platform.platform())} ({platform.machine()}); required Ubuntu 22+"))
        p = _cmd(["systemctl", "get-default"]) if shutil.which("systemctl") else None
        target = p.stdout.strip() if p is not None and p.returncode == 0 else ""
        r.append(Result(g, "Boot target (systemctl get-default)", PASS if target == "graphical.target" else WARN,
                        target or "unreadable"))
        pkgs = []
        if shutil.which("dpkg-query"):
            for pkg in ("ubuntu-desktop-minimal", "ubuntu-desktop", "gnome-shell"):
                q = _cmd(["dpkg-query", "-W", "-f=${Status}", pkg])
                if q is not None and "install ok installed" in q.stdout:
                    pkgs.append(pkg)
        r.append(Result(g, "Desktop packages", PASS if pkgs else WARN,
                        ", ".join(pkgs) or "ubuntu-desktop(-minimal) / gnome-shell not installed"))
    else:
        r.append(Result(g, "Operating system", INFO, f"{platform.platform()} — not Linux (local machine?)"))
    sess = ce.check_desktop()[0]
    r.append(Result(g, sess.check, PASS if sess.status == PASS else INFO,
                    sess.detail if sess.status == PASS else
                    f"{sess.detail} — expected in a terminal / SSH session; R1 is decided by the boot target and packages"))
    return r


def find_intellij() -> Path | None:
    """The installed IntelliJ (real install folders first, then the launcher on PATH); Ultimate if present."""
    home, idea = os.path.expanduser("~"), "*[Ii][Dd][Ee][Aa]*"
    pats = (f"/opt/{idea}/bin/idea.sh", f"/opt/*/{idea}/bin/idea.sh", "/snap/intellij-idea-ultimate/current/bin/idea.sh",
            f"{home}/.local/share/JetBrains/Toolbox/apps/{idea}/bin/idea.sh",
            f"{home}/.local/share/JetBrains/Toolbox/apps/{idea}/*/*/bin/idea.sh",
            "/Applications/IntelliJ IDEA*.app", f"{home}/Applications/IntelliJ IDEA*.app")
    cands = [c for pat in pats for c in sorted(glob.glob(pat))]
    cands += [shutil.which(x) for x in ("idea", "idea.sh", "intellij-idea-ultimate")]
    found = list(dict.fromkeys(Path(c).resolve() for c in cands if c))
    return next((p for p in found if intellij_install(p)[1].get("productCode") == "IU"), found[0] if found else None)


def intellij_install(path: Path) -> tuple[Path, dict]:
    """→ (install root — plugins/ lives here, product-info.json content)."""
    if path.suffix == ".app":
        root, info = path / "Contents", path / "Contents" / "Resources" / "product-info.json"
    else:
        root = path.parent.parent if path.parent.name == "bin" else path.parent
        info = root / "product-info.json"
    try:
        return root, json.loads(info.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return root, {}


def req_r2(a) -> list:
    g = "R2"
    p = find_intellij()
    if p is None:
        return [Result(g, "IntelliJ IDEA", WARN, "not found (PATH, /opt, snap, Toolbox)")]
    _, d = intellij_install(p)
    label = f"{d.get('name', 'IntelliJ IDEA')} {d.get('version', '')}".strip() + f" · {p}"
    code = d.get("productCode")
    if code == "IU" or "ultimate" in str(d.get("name", "")).lower():
        st, detail = PASS, label
    elif code == "IC":
        st, detail = WARN, f"Community edition — no Database Tools, Ultimate required: {label}"
    else:
        st, detail = WARN, f"edition unreadable (no product-info.json): {p}"
    return [Result(g, "IntelliJ IDEA Ultimate", st, detail),
            Result(g, "License", INFO, "activation is not visible from the terminal (shown when IntelliJ opens)")]


def req_r3(a) -> list:
    g = "R3"
    p = find_intellij()
    dirs = [intellij_install(p)[0] / "plugins"] if p else []
    home = os.path.expanduser("~")
    dirs += [Path(x) for x in glob.glob(f"{home}/.local/share/JetBrains/*") if "Toolbox" not in x]   # user plugins
    dirs += [Path(x) for x in glob.glob(f"{home}/Library/Application Support/JetBrains/*/plugins")]   # macOS
    names: set[str] = set()
    for d in dirs:
        if not d.is_dir():
            continue
        for e in d.iterdir():
            names.add(e.name.lower())
            if (e / "lib").is_dir():
                names.update(j.name.lower() for j in (e / "lib").glob("*.jar") if "jupyter" in j.name.lower())
    if p is None and not names:
        return [Result(g, "IntelliJ plugins", WARN, "IntelliJ not found (R2) — plugins not searched")]
    r = []
    for label, keys in (("Database Tools & SQL", ("database",)), ("Python", ("python",)), ("Jupyter", ("jupyter",))):
        hit = sorted(n for n in names if any(k in n for k in keys))
        r.append(Result(g, label, PASS if hit else WARN, ", ".join(hit[:4]) if hit else
                        "plugin folder not found — verify in IntelliJ → Settings → Plugins"))
    return r


SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "proc", "outputs", "data", ".cache", "snap",
             "Library", ".Trash"}


def find_files(pattern: str, roots: list[tuple[str, int]], limit: int = 10) -> list[Path]:
    """Files whose name matches `pattern` under roots: [(directory, max depth)] (heavy folders are skipped)."""
    found: list[Path] = []
    for root, max_depth in roots:
        base = Path(os.path.expanduser(root))
        if not base.is_dir():
            continue
        n0 = len(base.parts)
        for dirpath, dirnames, filenames in os.walk(base, onerror=lambda e: None):
            depth = len(Path(dirpath).parts) - n0
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS] if depth < max_depth else []
            for f in filenames:
                if fnmatch(f.lower(), pattern):
                    found.append(Path(dirpath) / f)
                    if len(found) >= limit:
                        return found
    return found


def req_r4(a) -> list:
    g = "R4"
    jars = find_files("intersystems-jdbc*.jar", [("/usr/irissys", 6), ("/opt", 6), ("/usr/share/java", 3),
                                                 ("/usr/local", 5), ("/srv", 4), ("~", 5)])
    r = [Result(g, "IRIS JDBC JAR (intersystems-jdbc*.jar)", PASS if jars else WARN,
                ", ".join(tilde(j) for j in jars[:5]) if jars else
                "not found — DHA should put the JAR from the IRIS install's dev/java/lib/ on the VM")]
    home = os.path.expanduser("~")
    xmls = (glob.glob(f"{home}/.config/JetBrains/*/options/*.xml") + glob.glob(f"{home}/.config/JetBrains/*/jdbc-drivers/*.xml")
            + glob.glob(str(REPO_ROOT / ".idea" / "*.xml")))
    reg = []
    for x in xmls:
        try:
            if "intersystems" in Path(x).read_text(encoding="utf-8", errors="ignore").lower():
                reg.append(tilde(Path(x)))
        except OSError:
            pass
    r.append(Result(g, "Driver registered in IntelliJ", INFO, ", ".join(reg[:3]) if reg else
                    "not seen in the settings files — check IntelliJ → Database → Drivers"))
    return r


def req_r5(a) -> list:
    tests = [Result("tests", "Unit tests + pip check", SKIP, "--quick")] if a.quick else ce.check_tests()
    explore = ce.check_explore()                   # installed ones on one line; missing ones one by one
    missing = [x for x in explore if x.status != PASS]
    compact = [Result("explore", "requirements-explore.txt", PASS if not missing else WARN,
                      f"{len(explore) - len(missing)}/{len(explore)} packages installed")] + missing
    return ce.check_python() + ce.check_core() + compact + tests


def req_r6(a) -> list:
    old = os.environ.get("GIT_TERMINAL_PROMPT")
    os.environ["GIT_TERMINAL_PROMPT"] = "0"        # do not ask for a token: if not cached, fail fast + hint
    try:
        r = ce.check_repo(github=True)
    finally:
        if old is None:
            os.environ.pop("GIT_TERMINAL_PROMPT", None)
        else:
            os.environ["GIT_TERMINAL_PROMPT"] = old
    if any(x.check.startswith("GitHub") and x.status == FAIL for x in r):
        r.append(Result("repo", "Hint", INFO, "if the token is not cached: sign in once with `git pull` at the repo root "
                                              "(docs/enclave_terminal.md §1, credential cache), then retry"))
    return r


def iris_target() -> tuple[str | None, int | None, str]:
    from sandbox.io import iris
    try:
        s = iris.connection_settings()
    except Exception:
        return DEFAULT_IRIS_HOST, DEFAULT_IRIS_PORT, "default — iris-setup not run yet"
    if s["driver"] == "pyodbc":
        return None, None, "ODBC string"
    t = iris.parse_url(s["_url"])
    return t.host, t.port, f"settings: {tilde(iris.credentials_file_path())} / environment variable"


def req_r7(a) -> list:
    g = "R7"
    if a.iris_sqlite:
        return [Result(g, "Network", INFO, "dry run (SQLite stand-in): no network check")]
    try:
        from sandbox.io import iris
    except Exception as e:
        return [Result(g, "io/iris.py", FAIL, f"cannot be imported (check R5 first): {type(e).__name__}: {e}")]
    host, port, src = iris_target()
    if host is None:
        return [Result(g, "Target", INFO, "ODBC string in use — no TCP check")]
    r = [Result(g, "Target", INFO, f"{host}:{port} ({src})")]
    try:
        ipaddress.ip_address(host)
        r.append(Result(g, "DNS", INFO, "IP address given — no DNS needed"))
    except ValueError:
        try:
            r.append(Result(g, "DNS", PASS, f"{host} → {', '.join(iris.resolve_host(host, port)[:4])}"))
        except OSError as e:
            r.append(Result(g, "DNS", WARN, f"{host} does not resolve ({e}); DNS is optional in R7 → use the IP: "
                                            f"iris-setup --url jdbc:IRIS://<IP>:{port}/<NAMESPACE>"))
    try:
        r.append(Result(g, "TCP", PASS, f"{host}:{port} open ({iris.tcp_check(host, port):.0f} ms)"))
    except OSError as e:
        r.append(Result(g, "TCP", FAIL, f"{host}:{port} unreachable: {e} — the firewall rule (R7) is on DHA's side"))
    return r


def schema_access(conn, max_schemas: int = 12) -> list:
    """Visible schemas and a SELECT on the first table of each (row content is not printed)."""
    from sandbox.io import explore

    g = "iris"
    sch = explore.list_schemas(conn)
    if sch.empty:
        return [Result(g, "Schemas", WARN, "no schema visible (system schemas excluded): is the namespace right, "
                                           "is there SELECT permission? (R8)")]
    r = [Result(g, "Schemas", PASS, f"{len(sch)} schemas · {int(sch['tables'].sum())} tables · "
                                    f"{int(sch['views'].sum())} views visible (system schemas excluded)")]
    ok, bad, rows = [], [], False
    for s in sch["schema"].head(max_schemas):
        t = explore.list_tables(conn, s)
        if t.empty:
            continue
        tb = t["table"].iloc[0]
        try:
            got = explore.run_query(conn, explore.limited(conn, f"1 AS x FROM {explore.ident(s, tb)}", 1))
            ok.append(s)
            rows = rows or len(got) > 0
        except Exception as e:
            bad.append(f"{s}.{tb}: {type(e).__name__}: {str(e)[:80]}")
    r.append(Result(g, "SELECT permission", PASS if ok and not bad else WARN if ok else FAIL,
                    f"first table read in {len(ok)}/{len(ok) + len(bad)} schemas"
                    + (f"; unreadable: {'; '.join(bad[:3])}" if bad else "")))
    r.append(Result(g, "Test query returned rows", PASS if rows else WARN,
                    "yes (content not printed)" if rows else "the tables tried are empty"))
    return r


def req_r8(a) -> list:
    results, conn = ce.check_iris(True, Path(a.iris_sqlite) if a.iris_sqlite else None, None)
    if conn is None:
        return results
    try:
        results += schema_access(conn)
    finally:
        conn.close()
    results.append(Result("iris", "Write permission", INFO, "not tested — this tool only sends SELECT (iris.assert_select)"))
    return results


def req_r9(a) -> list:
    return ce.check_resources()


REQS = {
    "R1": ("Desktop: Ubuntu 22+ desktop, graphical.target", req_r1),
    "R2": ("IDE: IntelliJ IDEA Ultimate", req_r2),
    "R3": ("IDE plugins: Database Tools & SQL, Python, Jupyter", req_r3),
    "R4": ("Database driver: IRIS JDBC (intersystems-jdbc JAR)", req_r4),
    "R5": ("Python ≥ 3.10, packages, pip check, unit tests", req_r5),
    "R6": ("Git + GitHub (read-only token, HTTPS 443)", req_r6),
    "R7": ("Network: VM → IRIS server, TCP 51772", req_r7),
    "R8": ("Read-only IRIS user: login, SELECT, schemas", req_r8),
    "R9": ("Resources: ≥ 4 vCPU, 16 GB RAM, 250 GB free disk", req_r9),
}


def cmd_req(a, out: Block, run) -> int:
    summary = []
    for rid in a.ids:
        title, fn = REQS[rid]
        out(f"[{rid}] {title}")
        try:
            res = fn(a)
        except Exception as e:
            res = [Result(rid, "check did not run", FAIL, f"{type(e).__name__}: {str(e)[:300]}")]
        print_results(out, res)
        summary.append((rid, worst(res)))
        out()
    out("Summary: " + " · ".join(f"{r} {s}" for r, s in summary))
    if run:
        run.log("requirements checked", **dict(summary))
    return 1 if any(s == FAIL for _, s in summary) else 0


# --------------------------------------------------------------------------
# IRIS access
# --------------------------------------------------------------------------
def _ask(prompt: str) -> str:
    """Question (terminal or redirected input); empty if there is no input."""
    try:
        return input(prompt).strip()
    except (EOFError, OSError, RuntimeError):
        return ""


def cmd_iris_setup(a, out: Block, run) -> int:
    from sandbox.io import iris

    path = iris.credentials_file_path()
    cur = iris.read_credentials_file(path)
    url = a.url or (f"jdbc:IRIS://{a.host}:{a.port}/{a.namespace}" if a.namespace else None)
    if not url:
        print(f"IRIS connection settings → {tilde(path)} (the password is not written to the file)")
        if cur.get(iris.ENV_URL):
            print(f"  current: {cur[iris.ENV_URL]} · user {cur.get(iris.ENV_USER, '?')}")
        ans = _ask(f"Namespace (from DHA; host {a.host}:{a.port}) or the full string jdbc:IRIS://host:port/NAMESPACE: ")
        url = ans if ("://" in ans or ans.lower().startswith("jdbc:")) else \
            (f"jdbc:IRIS://{a.host}:{a.port}/{ans}" if ans else cur.get(iris.ENV_URL))
    user = a.user
    if not user:
        default = cur.get(iris.ENV_USER, "")
        user = _ask(f"Read-only IRIS user{f' [{default}]' if default else ''}: ") or default
    if not url or not user:
        raise ValueError(f"connection string and user required: {CMD} iris-setup --namespace NS --user USER")
    target = iris.parse_url(url)
    if any(ch.isspace() for ch in user):
        raise ValueError("the user name cannot contain whitespace")
    if path.resolve().is_relative_to(REPO_ROOT):
        raise ValueError(f"{path} is inside the repo — it must live outside it (it could end up in git)")
    old = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    if old and not a.yes:
        if _ask(f"{tilde(path)} exists — replace the URL and user lines (other lines are kept)? [y/N]: ").lower() \
                not in ("e", "evet", "y", "yes"):
            out(f"Unchanged: {tilde(path)} (--yes updates without asking)")
            return 0
    keep = [ln for ln in old if ln.strip() and not ln.lstrip().startswith("#")
            and ln.split("=", 1)[0].strip() not in (iris.ENV_URL, iris.ENV_USER)]
    text = "\n".join([f"# NABIDH IRIS connection — tools/enclave.py iris-setup, {dt.date.today()}. "
                      "Outside the repo, chmod 600.", f"{iris.ENV_URL}={url}", f"{iris.ENV_USER}={user}", *keep]) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)
    has_pw = any(ln.split("=", 1)[0].strip() == iris.ENV_PASSWORD for ln in keep)
    out(f"Written: {tilde(path)} (chmod 600)")
    out(f"Target: {target} · user: {user}")
    out("Password: " + ("in the file (already there, kept)" if has_pw else
                        "not in the file → asked when connecting (to keep it for the session: docs/enclave_terminal.md §3)"))
    out(f"Next: {CMD} req R7 R8")
    if run:
        run.log("iris credentials written", path=tilde(path), target=str(target), user=user, password_in_file=has_pw)
    return 0


def needs_password(a) -> bool:
    if a.cmd in ("schemas", "tables", "columns", "values", "checks", "find", "count", "mapping"):
        return True
    if a.cmd == "req":
        return "R8" in a.ids
    if a.cmd == "run":
        return a.step in ("ingest", "all") and not a.snapshot
    return False


def ensure_password(a) -> None:
    """If no password is set, asks once and puts it only into this process's environment (subprocesses — ingest — use it too)."""
    if getattr(a, "iris_sqlite", None):
        return
    try:
        from sandbox.io import iris
        s = iris.connection_settings()
    except Exception:
        return                                     # no settings → a clear error when connecting
    if s["driver"] == "pyodbc" or os.environ.get(iris.ENV_PASSWORD) or iris.read_credentials_file().get(iris.ENV_PASSWORD):
        return
    if not iris.can_prompt():
        return
    pw = getpass.getpass(f"IRIS password ({s['user']}@{s['target']}): ")
    if pw:
        os.environ[iris.ENV_PASSWORD] = pw


def cohort_alias(name: str) -> str:
    """Cohort short name → IRIS schema (IRIS_COHORTS in the adapter): 'c1.Patient' → '<C1 schema>.Patient', 'c2' →
    '<C2 schema>'. No C1 / C2 shell variable needed. Other names stay as they are."""
    head, dot, rest = str(name).partition(".")
    if head.strip().lower() not in ("c1", "c2", "c3"):
        return name
    from sandbox.io.adapters import nabidh
    hit = nabidh.IRIS_COHORTS.get(head.strip().lower())
    return f"{hit['schema']}{dot}{rest}" if hit else name


def connect(a):
    """→ (DB-API connection, short name of the target). --iris-sqlite: dry-run SQLite files instead of IRIS."""
    from sandbox.io import iris
    from sandbox.io.adapters import nabidh

    if a.iris_sqlite:
        sq = Path(a.iris_sqlite).resolve()
        files = {v["schema"]: sq / f"{c}.sqlite" for c, v in nabidh.IRIS_COHORTS.items()
                 if v.get("schema") and (sq / f"{c}.sqlite").is_file()}
        if not files:
            raise FileNotFoundError(f"no <c1|c2|c3>.sqlite under {sq} (tools/make_nabidh_dryrun.py creates them)")
        return iris.sqlite_standin(files), f"SQLite stand-in (dry run): {sq.name}/"
    s = iris.connection_settings()
    try:
        conn = iris.connect()
    except Exception as e:
        raise RuntimeError(f"could not connect to IRIS ({s['target']}): {type(e).__name__}: {str(e)[:300]} "
                           f"— diagnose: {CMD} req R7 R8") from None
    return conn, f"IRIS {s['target']}"


# --------------------------------------------------------------------------
# IRIS exploration (io/explore.py)
# --------------------------------------------------------------------------
def cmd_schemas(a, out: Block, run) -> int:
    from sandbox.io import explore

    conn, target = connect(a)
    try:
        df = explore.list_schemas(conn, a.all, a.like)
    finally:
        conn.close()
    out(f"{target} — {len(df)} schemas" + ("" if a.all else " (system schemas hidden; all: --all)")
        + (f", name contains '{a.like}'" if a.like else ""))
    out.table(df, a.max_rows)
    out(f"Next: {CMD} tables SCHEMA")
    return 0


def cmd_tables(a, out: Block, run) -> int:
    from sandbox import sdc
    from sandbox.io import explore

    conn, target = connect(a)
    try:
        df = explore.list_tables(conn, a.schema)
        if df.empty:
            close = explore._close(a.schema, explore.list_schemas(conn, include_system=True)["schema"])
            out(f"{target} — no such schema, or none of its tables are visible: {a.schema}"
                + (f" · close names: {', '.join(close)}" if close else f" · list: {CMD} schemas"))
            return 1
        if a.like:
            df = df[df["table"].astype(str).str.contains(a.like, case=False, regex=False)]
        shown = df.head(a.max_rows).copy()
        if not a.no_count:
            counts = []
            for s, t in zip(shown["schema"], shown["table"]):
                try:
                    counts.append(sdc.fmt_count(explore.count_rows(conn, s, t)))
                except Exception as e:
                    counts.append(f"unreadable ({type(e).__name__})")
            shown["rows"] = counts
    finally:
        conn.close()
    schema = df["schema"].iloc[0] if len(df) else a.schema
    out(f"{target} · {schema} — {len(df)} tables / views" + (f" (name contains '{a.like}')" if a.like else ""))
    cols = ["table", "type"] + ([] if a.no_count else ["rows"])
    out.table(shown[cols], a.max_rows)
    if len(df) > len(shown):
        out(f"  ... +{len(df) - len(shown)} more tables (--max-rows / --like)")
    out(f"Next: {CMD} columns {schema}.TABLE")
    return 0


def cmd_columns(a, out: Block, run) -> int:
    from sandbox import sdc
    from sandbox.io import explore

    conn, target = connect(a)
    try:
        s, t = explore.resolve_table(conn, a.table)
        n_rows, n_smp, prof = explore.table_profile(conn, s, t, a.sample, a.where)
    finally:
        conn.close()
    out(f"{target} · {s}.{t} — {sdc.fmt_count(n_rows)} rows · {len(prof)} columns · profile: first {n_smp} rows"
        + (f" · WHERE {a.where}" if a.where else ""))
    out.table(prof.rename(columns={"filled_pct": "filled%", "shape": "shape (most common)"}), a.max_rows)
    out("shape: digit→9, run of letters→a (2023-01-05→9999-99-99, E11.9→a99.9). filled% and distinct are from the "
        "sample. values 'hidden' = sensitive name or ID-like")
    out(f"Next: {CMD} values {s}.{t} COLUMN")
    return 0


def _fmt_q(x) -> str:
    return f"{x:.4g}" if isinstance(x, float) else str(x)


def cmd_values(a, out: Block, run) -> int:
    from sandbox import sdc
    from sandbox.io import explore

    conn, target = connect(a)
    try:
        s, t = explore.resolve_table(conn, a.table)
        v = explore.value_counts(conn, s, t, a.column, a.where, a.patient_col, a.top, a.sample, a.list)
    finally:
        conn.close()
    k, prof, pk = explore.threshold(), v["profile"], v["patient_col"]
    pct = 100 * v["filled"] / v["rows"] if v["rows"] else 0.0
    out(f"{target} · {s}.{t}.{v['column']} ({v['type']}) — {sdc.fmt_count(v['rows'])} rows, "
        f"filled {sdc.fmt_count(v['filled'])} ({pct:.1f}%)" + (f" · WHERE {a.where}" if a.where else ""))
    out(f"Sample (first {v['sample_rows']} rows): kind {prof['kind']} · distinct {prof['distinct']}")
    if v["hidden"]:
        out(f"Values not shown: {v['hidden']}. Only shapes below.")
    elif v["distribution_only"]:
        out("Distribution (sample): " + (" · ".join(f"{q} {_fmt_q(x)}" for q, x in v["quantiles"].items())
                                         if v["quantiles"] else "not computable (sample < 10)"))
        out("  (date / continuous number: percentiles instead of a value list; --list for the list)")
    else:
        out("Shown: " + (f"only values seen in ≥ {k} distinct patients (patient key: {pk})" if pk else
                         f"only values seen in ≥ {k} rows (no patient key found; --patient-col COLUMN)"))
        out.table(v["values"].rename(columns={"v": "value", "n": "rows", "np": "patients"}), a.top)
        rs, rt = v["rest_small"], v["rest_top"]
        if rt["values"]:
            out(f"  + {rt['values']} values beyond the top {a.top} ({sdc.fmt_count(rt['rows'])} rows) — raise with --top")
        if rs["values"]:
            out(f"  + {rs['values']} values < {k} {'patients' if pk else 'rows'} ({sdc.fmt_count(rs['rows'])} rows in total) "
                "— not shown")
        if v["truncated"]:
            out(f"  (read the {explore.GROUP_ROWS} most common values; there are more)")
        if v["quantiles"]:
            out("Distribution (sample): " + " · ".join(f"{q} {_fmt_q(x)}" for q, x in v["quantiles"].items()))
    out("Shapes (sample, %):")
    out.table(v["shapes"].rename(columns={"pct": "%"}), 10)
    return 0


# SQL pieces for the smoking check (1s): tobacco items as SOURCES['social_history']['filter'], usable = not Unknown /
# Other / empty, smoking diagnosis codes (codelists smoking_current / smoking_ex, dotted as in Diagnosis_Code)
SMOKING_ITEMS_SQL = "SocialHabitCategory_Code IN ('Smoking', 'Cigarettes', 'Cigars', 'Cigarettes,Cigars', 'Tobacco')"
SMOKING_USABLE_SQL = ("SocialHabitQty_Description IS NOT NULL AND "
                      "UPPER(TRIM(SocialHabitQty_Description)) NOT IN ('UNKNOWN', 'OTHER', '')")
SMOKING_DX_SQL = "(Diagnosis_Code LIKE 'F17%' OR Diagnosis_Code LIKE 'Z72.0%' OR Diagnosis_Code LIKE 'Z87.891%')"

# Phase 1 step 1 value checks (docs/faz1_c1_c2.md §1) for `checks`: id → (title, [(table, column, top, where)]).
# Each query is the `values` command on every cohort given (≥ 10 patient rule; continuous numbers → percentiles only).
VITAL_CODES = ("39156-5", "8302-2", "3141-9")          # BMI, height, weight (Observation has no unit column)
CHECKS = {
    "1a": ("smoking item", [
        ("SocialHistory", "SocialHabitCategory_Code", 30, None),         # _Description: C3 only
        ("SocialHistory", "SocialHabitQty_Description", 30, None)]),
    "1c": ("lab and vital units", [
        ("LabResultItem", "TestItemCode_Code", 40, None),
        ("LabResultItem", "ResultValueUnits", 30, None),
        *[("Observation", "ObservationValue", 30, f"ObservationCode_Code = '{k}'") for k in VITAL_CODES]]),
    "1d": ("codes: diagnosis, observation, family history, Xigduo drug code", [
        ("Diagnosis", "Diagnosis_Code", 40, None),
        ("Observation", "ObservationCode_Code", 40, None),
        ("FamilyHistory", "FamilyMember_Description", 30, None),
        ("FamilyHistory", "Diagnosis_Code", 30, None),
        # ingest 1.3.0: 134 rows per cohort with a cholecalciferol DDC code on Xigduo XR 5/1000 orders (1.4.0 uses
        # the name); which product code the source attached
        ("Medication", "DrugProduct_Code", 20, "UPPER(DrugProduct_Description) LIKE '%DAPAGLIFLOZIN%METFORMIN%'")]),
    # Why most C2 patients have no usable smoking status (NB1 2026-11-20: C2 smoking missing 84.8%, QDiabetes
    # computable 14.5%). Besides `values` entries: ("#columns", table) = column profile, ("#count", label, SELECT
    # with {t} = the cohort's schema) = number of rows the SELECT returns, ("#find", text) = tables / columns named so.
    "1s": ("smoking: where the status comes from and where it is lost", [
        ("#columns", "SocialHistory"),
        ("SocialHistory", "SocialHabitQty_Description", 30, "SocialHabitCategory_Code = 'Smoking'"),
        ("SocialHistory", "SocialHabitCategory_Code", 30, "UPPER(SocialHabitQty_Description) = 'UNKNOWN'"),
        ("SocialHistory", "EnteredOn", 30, None),
        ("#count", "patients (Patient.ID)", "SELECT DISTINCT ID FROM {t}.Patient"),
        ("#count", "patients with any SocialHistory row", "SELECT DISTINCT Patient FROM {t}.SocialHistory WHERE Patient IS NOT NULL"),
        ("#count", "patients with a tobacco item", "SELECT DISTINCT Patient FROM {t}.SocialHistory WHERE Patient IS NOT NULL AND " + SMOKING_ITEMS_SQL),
        ("#count", "patients with a tobacco item and a usable value (not Unknown / Other / empty)",
         "SELECT DISTINCT Patient FROM {t}.SocialHistory WHERE Patient IS NOT NULL AND " + SMOKING_ITEMS_SQL + " AND "
         + SMOKING_USABLE_SQL),
        ("#count", "patients whose tobacco records are all Unknown or empty",
         "SELECT Patient FROM {t}.SocialHistory WHERE Patient IS NOT NULL AND " + SMOKING_ITEMS_SQL
         + " GROUP BY Patient HAVING "
         "SUM(CASE WHEN SocialHabitQty_Description IS NULL OR UPPER(TRIM(SocialHabitQty_Description)) IN ('UNKNOWN', '') "
         "THEN 0 ELSE 1 END) = 0"),
        ("#count", "patients whose tobacco records are all Other",
         "SELECT Patient FROM {t}.SocialHistory WHERE Patient IS NOT NULL AND " + SMOKING_ITEMS_SQL
         + " GROUP BY Patient HAVING "
         "SUM(CASE WHEN UPPER(TRIM(SocialHabitQty_Description)) = 'OTHER' THEN 0 ELSE 1 END) = 0"),
        ("#count", "patients with a smoking diagnosis code (F17 / Z72.0 / Z87.891)",
         "SELECT DISTINCT Patient FROM {t}.Diagnosis WHERE Patient IS NOT NULL AND " + SMOKING_DX_SQL),
        ("#count", "patients with neither a SocialHistory row nor a smoking diagnosis code",
         "SELECT ID FROM {t}.Patient WHERE ID NOT IN (SELECT Patient FROM {t}.SocialHistory WHERE Patient IS NOT NULL) "
         "AND ID NOT IN (SELECT Patient FROM {t}.Diagnosis WHERE Patient IS NOT NULL AND " + SMOKING_DX_SQL + ")"),
        ("#find", "SMOK"),
        ("#find", "TOBAC")]),
}


def check_count(a, out: Block, sql: str) -> None:
    """`checks` count entry: how many rows the SELECT returns (< 10 suppressed); rows are not read."""
    from sandbox import sdc
    from sandbox.io import explore

    conn, _ = connect(a)
    try:
        n = explore.count_query(conn, sql)
    finally:
        conn.close()
    out(f"  {sdc.fmt_count(n)}")


def check_find(a, out: Block, text: str, schema: str) -> None:
    """`checks` find entry: the cohort schema's tables and columns whose name contains the text (names only)."""
    from sandbox.io import explore

    conn, _ = connect(a)
    try:
        tables, cols = explore.find(conn, text)
    finally:
        conn.close()
    tables = tables[tables["schema"].str.upper() == schema.upper()]
    cols = cols[cols["schema"].str.upper() == schema.upper()]
    out(f"  tables: {', '.join(tables['table']) or 'none'}")
    out("  columns: " + (", ".join(f"{t}.{c}" for t, c in zip(cols["table"], cols["column"])) or "none"))


def cmd_checks(a, out: Block, run) -> int:
    """All step 1 `values` queries in one block. A query that fails (missing table / column) is reported on one line
    and the rest still run; the exit code is 1 only if every query failed."""
    ids = list(CHECKS) if not a.ids or "all" in a.ids else a.ids
    done = failed = 0
    for cid in ids:
        title, queries = CHECKS[cid]
        out(f"### {cid} · {title} · cohorts {' '.join(a.cohorts)}")
        for cohort in a.cohorts:
            for entry in queries:
                out()
                try:
                    if entry[0] == "#count":
                        out(f"== {cid} · {cohort} · {entry[1]}")
                        check_count(a, out, entry[2].format(t=cohort_alias(cohort)))
                    elif entry[0] == "#columns":
                        out(f"== {cid} · {cohort}.{entry[1]} · column profile")
                        cmd_columns(argparse.Namespace(**{**vars(a), "table": cohort_alias(f"{cohort}.{entry[1]}"),
                                                          "where": None}), out, run)
                    elif entry[0] == "#find":
                        out(f"== {cid} · {cohort} · tables / columns whose name contains {entry[1]!r}")
                        check_find(a, out, entry[1], cohort_alias(cohort))
                    else:
                        table, column, top, where = entry
                        out(f"== {cid} · {cohort}.{table}.{column}" + (f" · WHERE {where}" if where else ""))
                        cmd_values(argparse.Namespace(**{**vars(a), "table": cohort_alias(f"{cohort}.{table}"),
                                                         "column": column, "top": top, "where": where,
                                                         "patient_col": "auto", "list": False}), out, run)
                    done += 1
                except Exception as e:
                    failed += 1
                    msg = str(e).strip().splitlines()[0][:200] if str(e).strip() else ""
                    out(f"  not available: {type(e).__name__}: {msg}")
        out()
    out(f"checks {' '.join(ids)}: {done} queries done, {failed} not available")
    return 1 if failed and not done else 0


def cmd_find(a, out: Block, run) -> int:
    from sandbox.io import explore

    conn, target = connect(a)
    try:
        tb, cl = explore.find(conn, a.text, a.all)
    finally:
        conn.close()
    out(f"{target} — names containing '{a.text}': {len(tb)} tables / views, {len(cl)} columns")
    if len(tb):
        out("Tables:")
        out.table(tb, a.max_rows)
    if len(cl):
        out("Columns:")
        out.table(cl, a.max_rows)
    return 0


def cmd_count(a, out: Block, run) -> int:
    from sandbox import sdc
    from sandbox.io import explore

    conn, target = connect(a)
    try:
        n = explore.count_query(conn, a.sql)
    finally:
        conn.close()
    if run:
        run.log("count query", sql=a.sql)
    out(f"{target}")
    out(f"Query: {a.sql[:300]}")
    out(f"Row count: {sdc.fmt_count(n)}")
    return 0


def cmd_mapping(a, out: Block, run) -> int:
    from sandbox.io.adapters import nabidh

    conn, target = connect(a)
    try:
        res = ce.check_mapping(conn, a.cohorts or None)
    finally:
        conn.close()
    out(f"{target} — adapter mapping (src/sandbox/io/adapters/nabidh.py)")
    out("IRIS_COHORTS = " + json.dumps(nabidh.IRIS_COHORTS, ensure_ascii=False))
    print_results(out, res)
    bad = [x for x in res if x.status in (WARN, FAIL)]
    out(f"Summary: {sum(x.status == PASS for x in res)} PASS · {len(bad)} missing"
        + (" → send this block: SOURCES / IRIS_COHORTS get updated and pushed → git pull → mapping again" if bad else
           f" → next: {CMD} run ingest --cohorts c1 c2"))
    return 1 if bad else 0


# --------------------------------------------------------------------------
# Phase 1 / Phase 2 steps and outputs
# --------------------------------------------------------------------------
def safe_table(df):
    """Output table to print into the block: refused if it has a patient-key column; < 10 suppressed in count columns."""
    from sandbox import sdc
    from sandbox.io import explore

    bad = [c for c in df.columns if explore.patient_key([c])]
    if bad:
        raise ValueError(f"may be patient-level (column {bad}) — not printed")
    cols = [c for c in df.columns if _COUNTISH.search(str(c)) and not _NOT_COUNT.search(str(c))]
    return sdc.suppress_small_counts(df, cols) if cols else df


def framework_pivot(df):
    """nb00/framework_match.csv (cohort × group, long) → % of patients per group, one column per cohort.
    A cell whose count is < 10 shows no % either (so the count cannot be recovered as percentage × N)."""
    small = df["patients_with_any"].astype(str).str.startswith("<")
    pct = df["pct_patients"].astype(object).where(~small, "<10 patients")
    wide = df.assign(pct=pct).pivot_table(index=["domain", "group"], columns="cohort", values="pct", aggfunc="first")
    wide.columns.name = None
    return wide.reset_index()


# Step statuses whose details the block's summary already reports: no error tail then (for ingest "schema_errors" the
# screen tail is the raw unmapped-values table, with counts < 10 not suppressed)
REPORTED_STATUSES = {"schema_errors"}


def failure_lines(lines: list[str]) -> list[str]:
    """Error summary: the traceback's last 'File …' line + the last two non-empty lines."""
    out = []
    tb = [ln.strip() for ln in lines if ln.strip().startswith('File "')]
    if tb:
        out.append("Where: " + tb[-1].replace(str(REPO_ROOT), ".")[:200])
    tail = [ln.strip() for ln in lines if ln.strip()][-(1 if tb else 2):]
    out += [f"Error: {ln[:240]}" for ln in tail]
    out.append("(Check that the error line holds no patient value; if it does, do not copy that line.)")
    return out


# Drug → ATC summary (ingest value_counts, source "medications"): (field, max rows, hide small values).
# Code / name lists never print a value seen in < 10 rows; counts are already suppressed in the file.
MED_FIELDS = [
    ("drug → ATC method", 20, False), ("drug code format", 10, False), ("rows dropped: no study drug class", 1, False),
    ("combination products (rows → several ATC rows)", 1, False), ("ATC (3 chars) after mapping", 20, False),
    ("drug code not ATC/DDC", 10, True), ("ATC ← drug_name (name match)", 15, True),
    ("drug_name without study drug class", 15, True),
    ("DDC: not a study drug class (DDC ingredients | route)", 15, True),
    ("DDC: non-systemic route (DDC ingredients | route | row route)", 10, True),
    ("DDC code without study class → name used", 1, False),
    ("DDC code without study class → name used: DDC ≠ name ATC ← name", 10, True),
    ("DDC code without study class, name has one (code kept)", 1, False),
    ("DDC code without study class, name has one (code kept): DDC ≠ name ATC ← name", 10, True),
]


# Family history summary (source "family_history"): the end of the field name matches (e.g. "condition | condition_text
# (non-diabetes, dropped)"). Text values with < 10 rows are not printed.
FH_FIELDS = [
    ("diabetes recognised by", 5, False), ("text only: Diagnosis_Code", 12, True), ("relation → degree", 12, True),
    ("(prediabetes, dropped)", 10, True),
    ("(non-diabetes, dropped)", 10, True), ("condition_text negated → negative", 5, True),
    ("second-degree relative in text", 5, True),
]


# Diagnosis clean-up (source "diagnoses"): Diagnosis_Code cells with several codes (split) and trailing dots (counts).
DX_FIELDS = [("code cell with several codes → one row each", 5, False), ("code: trailing dot removed", 1, False)]


# Lab summary (source "lab_results", LabResultItem): kept codes, value distribution per kind | unit (in groups with
# ≥ 10 patients; unit check), tests whose name looks glycaemic but whose code is not recognised, other dropped tests.
# Code / name lists never print a value with < 10 rows.
LAB_FIELDS = [
    ("study lab: code | unit | name", 15, True), ("study lab unit: delivered → canonical", 15, False),
    ("value by kind | unit", 15, False),
    ("value outside plausible range", 10, False),
    ("lab value non-numeric (raw)", 10, True), ("rows dropped: non-numeric value", 1, False),
    ("non-numeric value (dropped): kind | shape", 10, False), ("lab value: decimal comma read as point", 1, False),
    ("rows dropped: not a study lab", 1, False),
    ("rows dropped: study code, other test by name", 1, False),
    ("study code, other test by name (dropped): code | unit | name", 10, True),
    ("glycaemic-looking tests (dropped): code | unit | name", 20, True),
    ("other tests (dropped): code | unit | name", 15, True),
]


# Vital summary (source "observations"): value distribution per vital (no unit column; groups with ≥ 10 patients only)
VITAL_FIELDS = [("vital value by concept | unit", 10, False), ("height in metres → cm (1.2–2.3 × 100)", 1, False)]


def field_summary(v, source: str, fields, suffix: bool = False):
    import pandas as pd

    v = v[v["source"].eq(source)]
    parts = []
    for field, top, hide_small in fields:
        x = v[v["field"].str.endswith(field)] if suffix else v[v["field"].eq(field)]
        if hide_small:
            x = x[~x["n_rows"].astype(str).str.startswith("<")]
        parts.append(x.head(top))
    return pd.concat(parts)[["field", "value", "n_rows"]] if parts else v.iloc[0:0]


def medication_summary(v):
    return field_summary(v, "medications", MED_FIELDS)


def summary_ingest(d: Path, out: Block, a) -> None:
    import pandas as pd
    from sandbox import sdc

    for f in sorted((d / "ingest").glob("*_summary.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        c = f.name.split("_", 1)[0]
        out(f"== {c.upper()} (ingest v{s.get('ingest_version', '?')}): {sdc.fmt_count(s.get('n_patients'))} patients · "
            f"schema ERROR {s.get('schema_errors')} / "
            f"WARN {s.get('schema_warnings')} · unmapped value rows {sdc.fmt_count(s.get('unmapped_value_rows'))}")
        out("   rows: " + ", ".join(f"{t}={sdc.fmt_count(n)}" for t, n in (s.get("rows") or {}).items()))
        for name, src in (s.get("sources") or {}).items():
            extra = [f"{k}={sdc.fmt_count(v)}" for k, v in src.items()
                     if k.startswith(("unparseable_", "filtered_out_by_", "dropped_empty_", "dropped_no_date"))
                     and not k.endswith("_by_code") and v]
            extra += [f"{k}={v}" for k, v in src.items() if k.startswith("absent") and v]
            # labels with < 10 rows are not named (nabidh._labels)
            extra += [f"{k}: {v}" for k, v in src.items()
                      if (k.startswith("filtered_out_values_") or k.endswith("_by_code")) and v]
            if src.get("error"):
                extra.append(str(src["error"])[:120])
            out(f"   {name:16s} {str(src.get('status', '?')):18s} read={sdc.fmt_count(src.get('rows_read', '-'))} "
                + " ".join(extra))
        val = d / "ingest" / f"{c}_validation.csv"
        if val.is_file():
            v = pd.read_csv(val)
            v = v[v["severity"] != "INFO"]
            if len(v):
                out("   schema check (non-INFO):")
                out.table(safe_table(v), a.max_rows)
        vc = d / "ingest" / f"{c}_value_counts.csv"
        if vc.is_file():
            v_all = pd.read_csv(vc, dtype=str)
            v = v_all[v_all["value"].str.contains("unmapped", na=False)]
            if len(v):
                out("   unmapped values (to add to the adapter dictionaries; < 10 suppressed):")
                out.table(v, a.max_rows)
            m = medication_summary(v_all)
            if len(m):
                out("   drug → ATC (DDC code / drug name; code and name lists omit values with < 10 rows):")
                out.table(m, a.max_rows)
            dx = field_summary(v_all, "diagnoses", DX_FIELDS)
            if len(dx):
                out("   diagnoses (Diagnosis_Code clean-up):")
                out.table(dx, a.max_rows)
            lab = field_summary(v_all, "lab_results", LAB_FIELDS)
            if len(lab):
                out("   lab (LabResultItem; kind | unit distribution in ≥ 10 patients; code / name lists omit values "
                    "with < 10 rows):")
                out.table(lab, a.max_rows)
            vit = field_summary(v_all, "observations", VITAL_FIELDS)
            if len(vit):
                out("   vitals (Observation; no unit column; distribution in ≥ 10 patients — height ~150–180 cm, "
                    "weight ~60–100 kg, BMI ~25–32):")
                out.table(vit, a.max_rows)
            f = field_summary(v_all, "family_history", FH_FIELDS, suffix=True)
            if len(f):
                out("   family history (how diabetes was recognised; text lists omit values with < 10 rows):")
                out.table(f, a.max_rows)


def summary_tables(step: str):
    def show(d: Path, out: Block, a) -> None:
        import pandas as pd

        for rel, filt, cols in SUMMARY_TABLES[step]:
            f = d / rel
            if not f.is_file():
                continue
            df = pd.read_csv(f)
            if filt == "issues" and "severity" in df.columns:
                df = df[df["severity"] != "INFO"]
            elif filt == "framework_pivot":
                df = framework_pivot(df)
            elif filt == "group_all" and "group" in df.columns:
                df = df[df["group"].astype(str) == "all"]
            elif filt == "audit_notes":
                if "notes" not in df.columns:
                    continue
                df = df[df["kpi"].eq("Audit Trail Completeness") & df["notes"].fillna("").astype(str).ne("")]
                if df.empty:
                    continue
            elif filt == "completeness_notes":      # aggregates only (kpi._completeness_note, counts < 10 suppressed)
                if "notes" not in df.columns:
                    continue
                df = df[df["kpi"].eq("Data Completeness for Required Variables")
                        & df["notes"].fillna("").astype(str).ne("")]
                if df.empty:
                    continue
            if cols:
                df = df[[c for c in cols if c in df.columns]]
            out(f"-- {rel} ({len(df)} rows)")
            out.table(safe_table(df), a.max_rows)
    return show


SUMMARIES = {"ingest": summary_ingest, **{s: summary_tables(s) for s in SUMMARY_TABLES}}


def step_command(step: str) -> list[str]:
    """How `run` starts a step: the repo's script. A one-file bundle (tools/build_bundle.py) replaces this with the
    copy of the script it carries."""
    return [sys.executable, STEPS[step][0]]


class DeferredBlock(Block):
    """Collects block lines without printing. `run all` prints them into the real block only after the last step,
    so no step's screen output (which stays inside the enclave) falls between the COPY markers."""

    def __init__(self):
        super().__init__("")
        self.started = True                                # no header of its own

    def _emit(self, ln: str) -> None:
        self.lines.append(ln)


def cmd_run_all(a, out: Block, run) -> int:
    """`run all`: ingest → nb0 → nb1 → kpi in one block. Every step runs even if one before it fails (each NB / KPI
    block says which ingest its data came from); the last line lists the exit codes. Exit code 1 if any step's
    run ended other than success (an ingest with schema_errors counts as reported, not failed)."""
    cohorts = a.cohorts or ["c1", "c2"]
    codes, buf = [], DeferredBlock()
    for i, step in enumerate(RUN_ALL, 1):
        print(f"\n===== run all · {i}/{len(RUN_ALL)} · {step} =====", flush=True)
        buf(f"### {i}/{len(RUN_ALL)} · run {step}")
        q = argparse.Namespace(**{**vars(a), "step": step, "cohorts": cohorts if step == "ingest" else None})
        codes.append((step, cmd_run(q, buf, run), getattr(q, "statuses", set())))
        buf()
    for ln in buf.lines:
        out(ln)
    out("run all · exit codes: " + " · ".join(f"{s} {rc}" for s, rc, _ in codes))
    bad = [s for s, rc, st in codes if rc != 0 and not (s == "ingest" and st <= {"schema_errors"} and st)]
    return 1 if bad else 0


def cmd_run(a, out: Block, run) -> int:
    from sandbox.config import DATA_DIR, OUTPUT_DIR

    if a.step == "all":
        return cmd_run_all(a, out, run)
    cmd = step_command(a.step)
    if a.step == "ingest":
        cmd += ["--source", a.source]
        if a.snapshot:
            snap = DATA_DIR / f"{a.source.removesuffix('_iris')}_iris" / "raw"     # where ingest keeps its snapshot
            cmd += ["--raw-root", str(snap.relative_to(REPO_ROOT))]
        else:
            cmd += ["--input", "iris"] + (["--iris-sqlite", str(a.iris_sqlite)] if a.iris_sqlite else [])
        if a.cohorts:
            cmd += ["--cohorts", *a.cohorts]
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "SANDBOX_SOURCE": a.source,
           "SANDBOX_PARENT_RUN": run.run_id if run else ""}      # still open while the step runs (kpi skips it)
    if a.bootstrap_reps:
        env["SANDBOX_BOOTSTRAP_REPS"] = str(a.bootstrap_reps)
    if a.step == "kpi" and getattr(a, "allow_overrides", False):
        cmd += ["--allow-overrides"]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in OUTPUT_DIR.iterdir()}
    print(f"Running: SANDBOX_SOURCE={a.source} python {' '.join(cmd[1:])}\n"
          "(the screen output below stays inside the enclave; the summary to copy comes at the end)", flush=True)
    lines: list[str] = []
    t0 = time.time()
    with subprocess.Popen(cmd, cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, bufsize=1, errors="replace") as p:
        for line in p.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            lines.append(line.rstrip("\n"))
    rc = p.returncode
    if run:
        log = run.path(f"enclave/{a.step}.log")
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        run.register_output(log, f"run {a.step} full screen output (stays inside the enclave)")
    new = sorted(n for n in {p.name for p in OUTPUT_DIR.iterdir()} - before if not (run and n == run.run_id))
    out(f"Step: run {a.step} · source {a.source} · exit code {rc} · {time.time() - t0:.0f} s")
    if a.step != "ingest":
        out(f"Data: {data_versions(a.source)}")
    found, statuses = [], set()
    for n in new:
        m = OUTPUT_DIR / n / "run_manifest.json"
        if m.is_file():
            d = json.loads(m.read_text(encoding="utf-8"))
            found.append(OUTPUT_DIR / n)
            statuses.add(d.get("status"))
            out(run_line(n, d))
            if a.step == "kpi":
                for ln in kpi_input_lines(OUTPUT_DIR / n):
                    out(ln)
    a.statuses = statuses                                  # read by `run all`
    if not found:
        out("No run record found (the script stopped before opening its audit)")
    if rc != 0 and not statuses & REPORTED_STATUSES:
        for ln in failure_lines(lines):
            out(ln)
    for d in found:
        out()
        SUMMARIES[a.step](d, out, a)
    if run:
        out(f"Full screen output (inside the enclave): outputs/{run.run_id}/enclave/{a.step}.log")
    return rc


def resolve_run_dir(spec: str) -> Path:
    from sandbox.config import OUTPUT_DIR

    dirs = sorted(p for p in OUTPUT_DIR.iterdir() if p.is_dir() and p.name != "audit") if OUTPUT_DIR.is_dir() else []
    if spec in STEPS:
        cand = [p for p in dirs if f"_{STEPS[spec][1]}_" in p.name]
    elif spec == "last":
        cand = [p for p in dirs if "_enclave_" not in p.name]
    else:
        cand = [p for p in dirs if p.name.startswith(spec) or p.name.endswith(spec)]
    if not cand:
        raise LookupError(f"run not found: {spec} (step name: {', '.join(STEPS)}, 'last' or a run_id)")
    return cand[-1]


def cmd_show(a, out: Block, run) -> int:
    import pandas as pd

    d = resolve_run_dir(a.run)
    csvs = sorted(str(p.relative_to(d)) for p in d.rglob("*.csv"))
    if not a.path:
        out(f"{d.name} — {len(csvs)} tables:")
        for c in csvs:
            out(f"  {c}")
        out(f"Print: {CMD} show {a.run} FILE")
        return 0
    f = (d / a.path).resolve()
    if not f.is_relative_to(d.resolve()) or not f.is_file():
        raise LookupError(f"{a.path} not found; {d.name} tables: {', '.join(csvs[:30])}")
    if f.suffix.lower() != ".csv":
        raise ValueError("only .csv tables are printed")
    df = pd.read_csv(f)
    out(f"{d.name}/{a.path} — {len(df)} rows")
    out.table(safe_table(df), a.max_rows)
    return 0


def cmd_last(a) -> int:
    from sandbox.config import OUTPUT_DIR

    blocks = sorted(OUTPUT_DIR.glob("*/enclave/block.txt"))
    if not blocks:
        print("No saved block")
        return 1
    text = blocks[-1].read_text(encoding="utf-8")
    print(text, end="")                                    # reprint only: not appended to the day's file again
    m = re.search(r" \| (\d{4}-\d{2}-\d{2}) \d{2}:\d{2} UTC \| ", text.split("\n", 1)[0])
    p = day_log(dt.datetime.strptime(m.group(1), "%Y-%m-%d")) if m else None
    if p and p.is_file() and text.split("\n", 1)[0] in p.read_text(encoding="utf-8"):
        print(f"Already in {repo_rel(p)} (not saved again)")
    return 0


HANDLERS = {"req": cmd_req, "iris-setup": cmd_iris_setup, "schemas": cmd_schemas, "tables": cmd_tables,
            "columns": cmd_columns, "values": cmd_values, "checks": cmd_checks, "find": cmd_find, "count": cmd_count,
            "mapping": cmd_mapping, "run": cmd_run, "show": cmd_show}


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--iris-sqlite", type=Path, default=None,
                        help="dry run: <dir>/<cohort>.sqlite instead of IRIS (tools/make_nabidh_dryrun.py)")
    common.add_argument("--max-rows", type=int, default=60, help="max rows in tables (default 60)")
    ap = argparse.ArgumentParser(prog="enclave.sh", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 description="Enclave terminal tool — guide: docs/enclave_terminal.md",
                                 epilog="The result is printed between '----8<---- COPY START' and '----8<---- COPY END'.")
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND")

    p = sub.add_parser("req", parents=[common], help="VM requirement: R1 … R9 or all")
    p.add_argument("ids", nargs="+", metavar="R", help="R1 … R9 (several allowed) or all")
    p.add_argument("--quick", action="store_true", help="R5: skip the unit tests and pip check")

    p = sub.add_parser("iris-setup", help="~/.nabidh_iris: IRIS connection string + user (password not written)")
    p.add_argument("--namespace", help="namespace from DHA (host/port default)")
    p.add_argument("--url", help="full string: jdbc:IRIS://host:port/NAMESPACE (e.g. an IP instead of the host)")
    p.add_argument("--user", help="read-only IRIS user")
    p.add_argument("--host", default=DEFAULT_IRIS_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_IRIS_PORT)
    p.add_argument("--yes", action="store_true", help="update an existing file without asking")

    p = sub.add_parser("schemas", parents=[common], help="schemas in the namespace (table / view counts)")
    p.add_argument("--all", action="store_true", help="show system schemas too")
    p.add_argument("--like", help="text the name contains")

    p = sub.add_parser("tables", parents=[common], help="a schema's tables + row counts")
    p.add_argument("schema", metavar="SCHEMA", help="schema name or cohort: c1 / c2 / c3")
    p.add_argument("--like", help="text the table name contains")
    p.add_argument("--no-count", action="store_true", help="skip row counts (fast on a large schema)")

    p = sub.add_parser("columns", parents=[common], help="a table's columns: type, fill rate, shape, kind")
    p.add_argument("table", metavar="SCHEMA.TABLE", help="e.g. c1.Patient (cohort → schema) or SCHEMA.Patient")
    p.add_argument("--sample", type=int, default=5000, help="profile sample (first N rows)")
    p.add_argument("--where", help="SQL condition (e.g. \"PatientType = 'C1'\")")

    p = sub.add_parser("values", parents=[common], help="value distribution of a column (≥ 10 patients)")
    p.add_argument("table", metavar="SCHEMA.TABLE", help="e.g. c1.Patient (cohort → schema) or SCHEMA.Patient")
    p.add_argument("column", metavar="COLUMN")
    p.add_argument("--top", type=int, default=30)
    p.add_argument("--where", help="SQL condition")
    p.add_argument("--patient-col", default="auto", help="patient key column (auto / COLUMN / none)")
    p.add_argument("--sample", type=int, default=5000)
    p.add_argument("--list", action="store_true", help="value list for dates / continuous numbers too (≥ 10 patient rule)")

    p = sub.add_parser("checks", parents=[common], help="Phase 1 step 1 value checks in one block: 1a 1c 1d 1s or all")
    p.add_argument("ids", nargs="*", metavar="ID", help="1a (smoking item), 1c (lab / vital units), 1d (codes), "
                                                         "1s (where smoking status is lost); default all")
    p.add_argument("--cohorts", nargs="+", choices=["c1", "c2", "c3"], default=["c1", "c2"], help="default c1 c2")
    p.add_argument("--sample", type=int, default=5000)

    p = sub.add_parser("find", parents=[common], help="tables and columns whose name contains the text")
    p.add_argument("text", metavar="TEXT")
    p.add_argument("--all", action="store_true", help="search system schemas too")

    p = sub.add_parser("count", parents=[common], help="row count of a SELECT (rows are not read)")
    p.add_argument("sql", metavar='"SELECT ..."')

    p = sub.add_parser("mapping", parents=[common], help="do the adapter SOURCES / IRIS_COHORTS hold in IRIS")
    p.add_argument("cohorts", nargs="*", choices=["c1", "c2", "c3"], metavar="COHORT")

    p = sub.add_parser("run", parents=[common], help="run a step: ingest, nb0, nb1, nb2, kpi; all = ingest → nb0 → nb1 → kpi")
    p.add_argument("step", choices=[*STEPS, "all"])
    p.add_argument("--cohorts", nargs="+", choices=["c1", "c2", "c3"], help="ingest: cohorts")
    p.add_argument("--source", default="nabidh", help="SANDBOX_SOURCE / ingest --source (default nabidh)")
    p.add_argument("--snapshot", action="store_true", help="ingest: from the last snapshot, without going to IRIS")
    p.add_argument("--bootstrap-reps", type=int, default=None, help="nb2: SANDBOX_BOOTSTRAP_REPS")
    p.add_argument("--allow-overrides", action="store_true",
                   help="kpi: also use runs with parameter overrides (SANDBOX_PARAMS) — exploratory KPI table")

    p = sub.add_parser("show", parents=[common], help="print a run's output table (counts suppressed)")
    p.add_argument("run", metavar="RUN", help="step name (ingest, nb0, nb1, nb2, kpi), last or a run_id")
    p.add_argument("path", nargs="?", metavar="FILE", help="e.g. nb01/score_summary.csv (empty: list)")

    sub.add_parser("last", help="reprint the last COPY block")
    sub.add_parser("help", help="this help")
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.cmd in (None, "help"):
        ap.print_help()
        return 0
    if a.cmd == "last":
        return cmd_last(a)
    import sandbox  # noqa: F401  (loads the untracked .env into the environment: SANDBOX_SOURCE, NABIDH_IRIS_PASSWORD …)
    for attr in ("table", "schema"):                 # c1.Patient → <C1 schema>.Patient
        if getattr(a, attr, None):
            setattr(a, attr, cohort_alias(getattr(a, attr)))
    if a.cmd == "req":
        ids = [x.upper() for x in a.ids]
        a.ids = list(REQS) if "ALL" in ids else ids
        unknown = [x for x in a.ids if x not in REQS]
        if unknown:
            ap.error(f"unknown requirement: {', '.join(unknown)} (R1 … R9 or all)")
    if a.cmd == "checks":                            # checked here: nargs="*" + choices fails on Python 3.10
        a.ids = [x.lower() for x in a.ids]
        unknown = [x for x in a.ids if x not in (*CHECKS, "all")]
        if unknown:
            ap.error(f"unknown check: {', '.join(unknown)} ({', '.join(CHECKS)} or all)")
    if needs_password(a):
        ensure_password(a)
    run = open_run(a.cmd)
    now = dt.datetime.now(dt.timezone.utc)
    utc = now.strftime("%Y-%m-%d %H:%M UTC")
    argv = safe_argv(argv)
    shown = shlex.join(argv)
    params = params_label()
    out = Block(f"{MARK_START} | enclave {shown[:120]}{'...' if len(shown) > 120 else ''} | "
                + (f"{params} | " if params else "") + f"{utc} | "
                f"ingest v{ingest_version()} | commit {commit_label()} | python {platform.python_version()} | "
                f"{run.run_id if run else 'no audit'} "
                f"{MARK}")
    try:
        rc = HANDLERS[a.cmd](a, out, run)
    except KeyboardInterrupt:
        out("Cancelled (Ctrl+C)")
        rc = 130
    except Exception as e:
        out(f"ERROR: {type(e).__name__}: {str(e)[:500]}")
        rc = 1
    out.close()
    finish_run(run, out, rc, argv, save_block(out, now))
    return rc


if __name__ == "__main__":
    sys.exit(main())
