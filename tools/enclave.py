"""Enclave terminal aracı: VM gereksinimlerini (R1–R9) tek tek dener, IRIS erişimini kurar, IRIS'i keşfeder
(IntelliJ Database aracının yerine), adapter eşlemesini denetler ve Faz 1 adımlarını çalıştırır.

Repo kökünden çalıştırılır (VM'de ~/Desktop/albert-dha/albert-dha-sandbox). Komutlar docs/enclave_terminal.md'den
kopyala-yapıştırla; projenin Python'unu tools/enclave.sh bulur:
  bash tools/enclave.sh req R5            # tek gereksinim; birkaç: req R7 R8; hepsi: req all
  bash tools/enclave.sh iris-setup        # ~/.nabidh_iris (URL + kullanıcı; şifre dosyaya yazılmaz)
  bash tools/enclave.sh schemas | tables SEMA | columns SEMA.TABLO | values SEMA.TABLO SUTUN
  bash tools/enclave.sh find smok | count "SELECT ..." | mapping c1 c2
  bash tools/enclave.sh run ingest|nb0|nb1|nb2|kpi
  bash tools/enclave.sh show nb1 nb01/score_summary.csv | last

Her komutun sonucu iki işaret satırı arasında basılır:
  ----8<---- KOPYALA BAŞ | <komut> | <zaman> | commit <sha> | <run_id> ----8<----
  ...
  ----8<---- KOPYALA SON ----8<----
Enclave dışına kopyalanacak olan yalnız bu bloktur. Blok yalnız meta veri ve özet içerir: tablo / sütun adları,
tipler, durumlar, sayımlar (< 10 → "<10"), değer şekilleri ve ≥ 10 hastada geçen kategorik değerler. Hasta düzeyi
değer basılmaz (kurallar: src/sandbox/io/explore.py). `run` adımlarının tam ekran çıktısı bloğun dışında kalır.
Her komut audit'lenir: outputs/<run_id>/enclave/block.txt (+ run adımında tam çıktı .log); `last` son bloğu
yeniden basar. IRIS'e yalnız SELECT gider; şifre basılmaz, dosyaya ve audit'e yazılmaz.

Bu dosya standart kütüphaneyle başlar: pandas eksikse de `req` çalışır ve eksikliği raporlar.
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

import check_environment as ce  # noqa: E402  (yalnız standart kütüphane)

Result, PASS, WARN, FAIL, SKIP, INFO = ce.Result, ce.PASS, ce.WARN, ce.FAIL, ce.SKIP, ce.INFO

DEFAULT_IRIS_HOST = "dhasbxnbprddb01.dha.ae"      # DHA'nın bağlantı dizesi (VM Requirements R7)
DEFAULT_IRIS_PORT = 51772
CMD = "bash tools/enclave.sh"   # repo kökünden
MARK = "----8<----"
MARK_END = f"{MARK} KOPYALA SON {MARK}"

# run adımları: script, audit run adı (outputs/<ts>_<ad>_<hex>)
STEPS = {
    "ingest": ("tools/ingest_nabidh.py", "ingest_nabidh"),
    "nb0": ("notebooks/00_data_profile.py", "nb00_data_profile"),
    "nb1": ("notebooks/01_c1_c2_feasibility.py", "nb01_c1_c2_feasibility"),
    "nb2": ("notebooks/02_c3_benchmark.py", "nb02_c3_benchmark"),
    "kpi": ("tools/kpi_report.py", "kpi_report"),
}
# run sonrası bloğa basılan özet tablolar: (dosya, satır filtresi, sütunlar)
SUMMARY_TABLES = {
    "nb0": [("nb00/schema_validation.csv", "issues", None), ("nb00/volume.csv", None, None),
            ("nb00/framework_match.csv", "framework_pivot", None), ("nb00/unmapped_codes.csv", None, None),
            ("nb00/kpi_preview.csv", None, None)],
    "nb1": [("nb01/score_computability.csv", None, None), ("nb01/score_missing_reasons.csv", None, None),
            ("nb01/c1_detection_rate.csv", None,
             ["cohort", "reference", "group", "score", "n", "n_computable", "n_flagged", "sens_computable",
              "ci_low", "ci_high", "threshold"]),
            ("nb01/score_summary.csv", None, None), ("nb01/joint_completeness.csv", None, None)],
    "nb2": [("nb02/coverage.csv", None, None), ("nb02/performance.csv", None, None)],
    "kpi": [("kpi/kpi_table.csv", None, ["kpi", "target", "actual", "met"])],
}
_COUNTISH = re.compile(r"(^n$|^np$|^n_|_n$|count|patients|^rows|_rows$|events)", re.IGNORECASE)
_NOT_COUNT = re.compile(r"(pct|percent|rate|ratio|share|sens|median|mean)", re.IGNORECASE)


# --------------------------------------------------------------------------
# Kopyalanacak blok + audit
# --------------------------------------------------------------------------
class Block:
    """Enclave dışına kopyalanacak çıktı. Başlık ilk yazımda basılır (öncesindeki sorular / adım çıktısı
    bloğa girmez); `close` bitiş işaretini basar. Satırlar audit için tutulur."""

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
            self("  (boş)")
            return
        for ln in df.head(max_rows).to_string(index=False).splitlines():
            self("  " + ln)
        if len(df) > max_rows:
            self(f"  ... +{len(df) - max_rows} satır daha (--max-rows ile artır)")

    def close(self) -> None:
        if not self.started:
            self("(çıktı yok)")
        self._emit(MARK_END)


def _git(*args: str) -> str:
    try:
        p = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def commit_label() -> str:
    sha = _git("rev-parse", "--short", "HEAD") or "?"
    return sha + ("+değişiklik" if _git("status", "--porcelain", "--", "src", "notebooks", "tools") else "")


def open_run(cmd: str):
    try:
        from sandbox.audit import Run
        return Run(f"enclave_{cmd.replace('-', '_')}", source=os.environ.get("SANDBOX_SOURCE"))
    except Exception as e:                       # outputs/ yazılamıyor vb. — blok yine basılır
        print(f"(audit açılamadı: {type(e).__name__}: {e})")
        return None


def finish_run(run, block: Block, rc: int, argv: list[str]) -> None:
    if run is None:
        return
    try:
        p = run.path("enclave/block.txt")
        p.write_text("\n".join(block.lines) + "\n", encoding="utf-8")
        run.register_output(p, "terminale basılan KOPYALA bloğu")
        run.log("enclave command", argv=argv, exit_code=rc)
        run.finish("success" if rc == 0 else "failed")
    except Exception as e:
        print(f"(audit yazılamadı: {type(e).__name__}: {e})")


def safe_argv(argv: list[str]) -> list[str]:
    """Blok başlığı / audit için argümanlar: --url'nin ';' / '?' sonrası (sürücü parametreleri) atılır."""
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
# R1–R9: VM gereksinimleri (Data Exploration Environment – VM Requirements)
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
        r.append(Result(g, "İşletim sistemi", PASS if ok else WARN,
                        f"{osr.get('PRETTY_NAME', platform.platform())} ({platform.machine()}); istenen Ubuntu 22+"))
        p = _cmd(["systemctl", "get-default"]) if shutil.which("systemctl") else None
        target = p.stdout.strip() if p is not None and p.returncode == 0 else ""
        r.append(Result(g, "Açılış hedefi (systemctl get-default)", PASS if target == "graphical.target" else WARN,
                        target or "okunamadı"))
        pkgs = []
        if shutil.which("dpkg-query"):
            for pkg in ("ubuntu-desktop-minimal", "ubuntu-desktop", "gnome-shell"):
                q = _cmd(["dpkg-query", "-W", "-f=${Status}", pkg])
                if q is not None and "install ok installed" in q.stdout:
                    pkgs.append(pkg)
        r.append(Result(g, "Masaüstü paketleri", PASS if pkgs else WARN,
                        ", ".join(pkgs) or "ubuntu-desktop(-minimal) / gnome-shell kurulu değil"))
    else:
        r.append(Result(g, "İşletim sistemi", INFO, f"{platform.platform()} — Linux değil (yerel makine?)"))
    sess = ce.check_desktop()[0]
    r.append(Result(g, sess.check, PASS if sess.status == PASS else INFO,
                    sess.detail if sess.status == PASS else
                    f"{sess.detail} — terminal / SSH oturumunda beklenen; R1'i açılış hedefi ve paketler belirler"))
    return r


def find_intellij() -> Path | None:
    """Kurulu IntelliJ (önce gerçek kurulum klasörleri, sonra PATH'teki başlatıcı); Ultimate varsa o."""
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
    """→ (kurulum kökü — plugins/ burada, product-info.json içeriği)."""
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
        return [Result(g, "IntelliJ IDEA", WARN, "bulunamadı (PATH, /opt, snap, Toolbox)")]
    _, d = intellij_install(p)
    label = f"{d.get('name', 'IntelliJ IDEA')} {d.get('version', '')}".strip() + f" · {p}"
    code = d.get("productCode")
    if code == "IU" or "ultimate" in str(d.get("name", "")).lower():
        st, detail = PASS, label
    elif code == "IC":
        st, detail = WARN, f"Community sürümü — Database Tools yok, Ultimate gerekli: {label}"
    else:
        st, detail = WARN, f"sürüm okunamadı (product-info.json yok): {p}"
    return [Result(g, "IntelliJ IDEA Ultimate", st, detail),
            Result(g, "Lisans", INFO, "etkinleştirme terminalden görülmez (IntelliJ açılınca)")]


def req_r3(a) -> list:
    g = "R3"
    p = find_intellij()
    dirs = [intellij_install(p)[0] / "plugins"] if p else []
    home = os.path.expanduser("~")
    dirs += [Path(x) for x in glob.glob(f"{home}/.local/share/JetBrains/*") if "Toolbox" not in x]   # kullanıcı eklentileri
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
        return [Result(g, "IntelliJ eklentileri", WARN, "IntelliJ bulunamadı (R2) — eklentiler aranamadı")]
    r = []
    for label, keys in (("Database Tools & SQL", ("database",)), ("Python", ("python",)), ("Jupyter", ("jupyter",))):
        hit = sorted(n for n in names if any(k in n for k in keys))
        r.append(Result(g, label, PASS if hit else WARN, ", ".join(hit[:4]) if hit else
                        "eklenti klasörü bulunamadı — IntelliJ → Settings → Plugins'te doğrula"))
    return r


SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "proc", "outputs", "data", ".cache", "snap",
             "Library", ".Trash"}


def find_files(pattern: str, roots: list[tuple[str, int]], limit: int = 10) -> list[Path]:
    """roots: [(dizin, en fazla derinlik)] altında adı `pattern`'e uyan dosyalar (ağır klasörler atlanır)."""
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
                "bulunamadı — DHA IRIS kurulumunun dev/java/lib/ altındaki JAR'ı VM'e koymalı")]
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
    r.append(Result(g, "IntelliJ'de sürücü kaydı", INFO, ", ".join(reg[:3]) if reg else
                    "ayar dosyalarında görülmedi — IntelliJ → Database → Drivers'ta kontrol et"))
    return r


def req_r5(a) -> list:
    tests = [Result("tests", "Unit testler + pip check", SKIP, "--quick")] if a.quick else ce.check_tests()
    explore = ce.check_explore()                   # kurulu olanlar tek satırda; eksikler tek tek
    missing = [x for x in explore if x.status != PASS]
    compact = [Result("explore", "requirements-explore.txt", PASS if not missing else WARN,
                      f"{len(explore) - len(missing)}/{len(explore)} paket kurulu")] + missing
    return ce.check_python() + ce.check_core() + compact + tests


def req_r6(a) -> list:
    old = os.environ.get("GIT_TERMINAL_PROMPT")
    os.environ["GIT_TERMINAL_PROMPT"] = "0"        # token sorulmasın: önbellekte yoksa hızlı FAIL + ipucu
    try:
        r = ce.check_repo(github=True)
    finally:
        if old is None:
            os.environ.pop("GIT_TERMINAL_PROMPT", None)
        else:
            os.environ["GIT_TERMINAL_PROMPT"] = old
    if any(x.check.startswith("GitHub") and x.status == FAIL for x in r):
        r.append(Result("repo", "İpucu", INFO, "token önbellekte değilse: repo kökünde `git pull` ile bir kez gir "
                                               "(docs/enclave_terminal.md §1, credential cache), sonra tekrar"))
    return r


def iris_target() -> tuple[str | None, int | None, str]:
    from sandbox.io import iris
    try:
        s = iris.connection_settings()
    except Exception:
        return DEFAULT_IRIS_HOST, DEFAULT_IRIS_PORT, "varsayılan — iris-setup henüz yapılmadı"
    if s["driver"] == "pyodbc":
        return None, None, "ODBC dizesi"
    t = iris.parse_url(s["_url"])
    return t.host, t.port, f"ayar: {tilde(iris.credentials_file_path())} / ortam değişkeni"


def req_r7(a) -> list:
    g = "R7"
    if a.iris_sqlite:
        return [Result(g, "Ağ", INFO, "prova (SQLite stand-in): ağ kontrolü yok")]
    try:
        from sandbox.io import iris
    except Exception as e:
        return [Result(g, "io/iris.py", FAIL, f"import edilemiyor (önce R5): {type(e).__name__}: {e}")]
    host, port, src = iris_target()
    if host is None:
        return [Result(g, "Hedef", INFO, "ODBC dizesi kullanılıyor — TCP kontrolü yapılmadı")]
    r = [Result(g, "Hedef", INFO, f"{host}:{port} ({src})")]
    try:
        ipaddress.ip_address(host)
        r.append(Result(g, "DNS", INFO, "IP adresi verilmiş — DNS gerekmez"))
    except ValueError:
        try:
            r.append(Result(g, "DNS", PASS, f"{host} → {', '.join(iris.resolve_host(host, port)[:4])}"))
        except OSError as e:
            r.append(Result(g, "DNS", WARN, f"{host} çözülmüyor ({e}); R7'de DNS opsiyonel → IP ile: "
                                            f"iris-setup --url jdbc:IRIS://<IP>:{port}/<NAMESPACE>"))
    try:
        r.append(Result(g, "TCP", PASS, f"{host}:{port} açık ({iris.tcp_check(host, port):.0f} ms)"))
    except OSError as e:
        r.append(Result(g, "TCP", FAIL, f"{host}:{port} erişilemiyor: {e} — firewall kuralı (R7) DHA'da"))
    return r


def schema_access(conn, max_schemas: int = 12) -> list:
    """Görünen şemalar ve her birinin ilk tablosunda SELECT (satır içeriği basılmaz)."""
    from sandbox.io import explore

    g = "iris"
    sch = explore.list_schemas(conn)
    if sch.empty:
        return [Result(g, "Şemalar", WARN, "hiç şema görünmüyor (sistem şemaları hariç): namespace doğru mu, "
                                           "SELECT yetkisi var mı? (R8)")]
    r = [Result(g, "Şemalar", PASS, f"{len(sch)} şema · {int(sch['tables'].sum())} tablo · "
                                    f"{int(sch['views'].sum())} view görünüyor (sistem şemaları hariç)")]
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
    r.append(Result(g, "SELECT yetkisi", PASS if ok and not bad else WARN if ok else FAIL,
                    f"{len(ok)}/{len(ok) + len(bad)} şemanın ilk tablosu okundu"
                    + (f"; okunamayan: {'; '.join(bad[:3])}" if bad else "")))
    r.append(Result(g, "Test sorgusu satır döndü", PASS if rows else WARN,
                    "evet (içerik basılmaz)" if rows else "denenen tablolar boş"))
    return r


def req_r8(a) -> list:
    results, conn = ce.check_iris(True, Path(a.iris_sqlite) if a.iris_sqlite else None, None)
    if conn is None:
        return results
    try:
        results += schema_access(conn)
    finally:
        conn.close()
    results.append(Result("iris", "Yazma yetkisi", INFO, "denenmez — bu araç yalnız SELECT gönderir (iris.assert_select)"))
    return results


def req_r9(a) -> list:
    return ce.check_resources()


REQS = {
    "R1": ("Masaüstü: Ubuntu 22+ masaüstü, graphical.target", req_r1),
    "R2": ("IDE: IntelliJ IDEA Ultimate", req_r2),
    "R3": ("IDE eklentileri: Database Tools & SQL, Python, Jupyter", req_r3),
    "R4": ("Veritabanı sürücüsü: IRIS JDBC (intersystems-jdbc JAR)", req_r4),
    "R5": ("Python ≥ 3.10, paketler, pip check, unit testler", req_r5),
    "R6": ("Git + GitHub (salt-okuma token, HTTPS 443)", req_r6),
    "R7": ("Ağ: VM → IRIS sunucusu, TCP 51772", req_r7),
    "R8": ("Salt-okuma IRIS kullanıcısı: giriş, SELECT, şemalar", req_r8),
    "R9": ("Kaynaklar: ≥ 4 vCPU, 16 GB RAM, 250 GB boş disk", req_r9),
}


def cmd_req(a, out: Block, run) -> int:
    summary = []
    for rid in a.ids:
        title, fn = REQS[rid]
        out(f"[{rid}] {title}")
        try:
            res = fn(a)
        except Exception as e:
            res = [Result(rid, "kontrol çalışmadı", FAIL, f"{type(e).__name__}: {str(e)[:300]}")]
        print_results(out, res)
        summary.append((rid, worst(res)))
        out()
    out("Özet: " + " · ".join(f"{r} {s}" for r, s in summary))
    if run:
        run.log("requirements checked", **dict(summary))
    return 1 if any(s == FAIL for _, s in summary) else 0


# --------------------------------------------------------------------------
# IRIS erişimi
# --------------------------------------------------------------------------
def _ask(prompt: str) -> str:
    """Soru (terminal ya da yönlendirilmiş girdi); girdi yoksa boş."""
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
        print(f"IRIS bağlantı ayarı → {tilde(path)} (şifre dosyaya yazılmaz)")
        if cur.get(iris.ENV_URL):
            print(f"  mevcut: {cur[iris.ENV_URL]} · kullanıcı {cur.get(iris.ENV_USER, '?')}")
        ans = _ask(f"Namespace (DHA'nın verdiği; host {a.host}:{a.port}) ya da tam dize jdbc:IRIS://host:port/NAMESPACE: ")
        url = ans if ("://" in ans or ans.lower().startswith("jdbc:")) else \
            (f"jdbc:IRIS://{a.host}:{a.port}/{ans}" if ans else cur.get(iris.ENV_URL))
    user = a.user
    if not user:
        default = cur.get(iris.ENV_USER, "")
        user = _ask(f"Salt-okuma IRIS kullanıcısı{f' [{default}]' if default else ''}: ") or default
    if not url or not user:
        raise ValueError(f"bağlantı dizesi ve kullanıcı gerekli: {CMD} iris-setup --namespace NS --user KULLANICI")
    target = iris.parse_url(url)
    if any(ch.isspace() for ch in user):
        raise ValueError("kullanıcı adında boşluk olamaz")
    if path.resolve().is_relative_to(REPO_ROOT):
        raise ValueError(f"{path} repo içinde — repo dışında olmalı (git'e girebilir)")
    old = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    if old and not a.yes:
        if _ask(f"{tilde(path)} var — URL ve kullanıcı satırları değişsin mi (diğer satırlar korunur)? [e/H]: ").lower() \
                not in ("e", "evet", "y", "yes"):
            out(f"Değiştirilmedi: {tilde(path)} (sormadan güncellemek için --yes)")
            return 0
    keep = [ln for ln in old if ln.strip() and not ln.lstrip().startswith("#")
            and ln.split("=", 1)[0].strip() not in (iris.ENV_URL, iris.ENV_USER)]
    text = "\n".join([f"# NABIDH IRIS bağlantısı — tools/enclave.py iris-setup, {dt.date.today()}. "
                      "Repo dışında, chmod 600.", f"{iris.ENV_URL}={url}", f"{iris.ENV_USER}={user}", *keep]) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)
    has_pw = any(ln.split("=", 1)[0].strip() == iris.ENV_PASSWORD for ln in keep)
    out(f"Yazıldı: {tilde(path)} (chmod 600)")
    out(f"Hedef: {target} · kullanıcı: {user}")
    out("Şifre: " + ("dosyada (önceden vardı, korundu)" if has_pw else
                     "dosyada yok → bağlanırken sorulur (oturum boyu tutmak: docs/enclave_terminal.md §3)"))
    out(f"Sonraki: {CMD} req R7 R8")
    if run:
        run.log("iris credentials written", path=tilde(path), target=str(target), user=user, password_in_file=has_pw)
    return 0


def needs_password(a) -> bool:
    if a.cmd in ("schemas", "tables", "columns", "values", "find", "count", "mapping"):
        return True
    if a.cmd == "req":
        return "R8" in a.ids
    if a.cmd == "run":
        return a.step == "ingest" and not a.snapshot
    return False


def ensure_password(a) -> None:
    """Şifre ayarlı değilse bir kez sorar ve yalnız bu sürecin ortamına koyar (alt süreçler — ingest — da kullanır)."""
    if getattr(a, "iris_sqlite", None):
        return
    try:
        from sandbox.io import iris
        s = iris.connection_settings()
    except Exception:
        return                                     # ayar yok → bağlanırken anlaşılır hata
    if s["driver"] == "pyodbc" or os.environ.get(iris.ENV_PASSWORD) or iris.read_credentials_file().get(iris.ENV_PASSWORD):
        return
    if not iris.can_prompt():
        return
    pw = getpass.getpass(f"IRIS şifresi ({s['user']}@{s['target']}): ")
    if pw:
        os.environ[iris.ENV_PASSWORD] = pw


def cohort_alias(name: str) -> str:
    """Kohort kısa adı → IRIS şeması (adapter'daki IRIS_COHORTS): 'c1.Patient' → '<C1 şeması>.Patient', 'c2' →
    '<C2 şeması>'. Shell'de C1 / C2 değişkeni gerekmez. Diğer adlar olduğu gibi kalır."""
    head, dot, rest = str(name).partition(".")
    if head.strip().lower() not in ("c1", "c2", "c3"):
        return name
    from sandbox.io.adapters import nabidh
    hit = nabidh.IRIS_COHORTS.get(head.strip().lower())
    return f"{hit['schema']}{dot}{rest}" if hit else name


def connect(a):
    """→ (DB-API bağlantısı, hedefin kısa adı). --iris-sqlite: IRIS yerine prova SQLite dosyaları."""
    from sandbox.io import iris
    from sandbox.io.adapters import nabidh

    if a.iris_sqlite:
        sq = Path(a.iris_sqlite).resolve()
        files = {v["schema"]: sq / f"{c}.sqlite" for c, v in nabidh.IRIS_COHORTS.items()
                 if v.get("schema") and (sq / f"{c}.sqlite").is_file()}
        if not files:
            raise FileNotFoundError(f"{sq} altında <c1|c2|c3>.sqlite yok (tools/make_nabidh_dryrun.py üretir)")
        return iris.sqlite_standin(files), f"SQLite stand-in (prova): {sq.name}/"
    s = iris.connection_settings()
    try:
        conn = iris.connect()
    except Exception as e:
        raise RuntimeError(f"IRIS'e bağlanılamadı ({s['target']}): {type(e).__name__}: {str(e)[:300]} "
                           f"— tanı: {CMD} req R7 R8") from None
    return conn, f"IRIS {s['target']}"


# --------------------------------------------------------------------------
# IRIS keşfi (io/explore.py)
# --------------------------------------------------------------------------
def cmd_schemas(a, out: Block, run) -> int:
    from sandbox.io import explore

    conn, target = connect(a)
    try:
        df = explore.list_schemas(conn, a.all, a.like)
    finally:
        conn.close()
    out(f"{target} — {len(df)} şema" + ("" if a.all else " (sistem şemaları gizli; hepsi: --all)")
        + (f", adında '{a.like}' geçen" if a.like else ""))
    out.table(df.rename(columns={"schema": "şema", "tables": "tablo", "views": "view"}), a.max_rows)
    out(f"Sonraki: {CMD} tables SEMA")
    return 0


def cmd_tables(a, out: Block, run) -> int:
    from sandbox import sdc
    from sandbox.io import explore

    conn, target = connect(a)
    try:
        df = explore.list_tables(conn, a.schema)
        if df.empty:
            close = explore._close(a.schema, explore.list_schemas(conn, include_system=True)["schema"])
            out(f"{target} — şema yok ya da tablosu görünmüyor: {a.schema}"
                + (f" · yakın adlar: {', '.join(close)}" if close else f" · listele: {CMD} schemas"))
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
                    counts.append(f"okunamadı ({type(e).__name__})")
            shown["rows"] = counts
    finally:
        conn.close()
    schema = df["schema"].iloc[0] if len(df) else a.schema
    out(f"{target} · {schema} — {len(df)} tablo / view" + (f" (adında '{a.like}')" if a.like else ""))
    cols = ["table", "type"] + ([] if a.no_count else ["rows"])
    out.table(shown[cols].rename(columns={"table": "tablo", "type": "tür", "rows": "satır"}), a.max_rows)
    if len(df) > len(shown):
        out(f"  ... +{len(df) - len(shown)} tablo daha (--max-rows / --like)")
    out(f"Sonraki: {CMD} columns {schema}.TABLO")
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
    out(f"{target} · {s}.{t} — {sdc.fmt_count(n_rows)} satır · {len(prof)} sütun · profil: ilk {n_smp} satır"
        + (f" · WHERE {a.where}" if a.where else ""))
    out.table(prof.rename(columns={"column": "sütun", "type": "tip", "filled_pct": "dolu%", "distinct": "farklı",
                                   "shape": "şekil (en sık)", "kind": "tür", "values": "değerler"}), a.max_rows)
    out("şekil: rakam→9, harf dizisi→a (2023-01-05→9999-99-99, E11.9→a99.9). dolu% ve farklı örneklemde. "
        "değerler 'gizli' = hassas ad ya da kimlik gibi")
    out(f"Sonraki: {CMD} values {s}.{t} SUTUN")
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
    out(f"{target} · {s}.{t}.{v['column']} ({v['type']}) — {sdc.fmt_count(v['rows'])} satır, "
        f"dolu {sdc.fmt_count(v['filled'])} (%{pct:.1f})" + (f" · WHERE {a.where}" if a.where else ""))
    out(f"Örneklem (ilk {v['sample_rows']} satır): tür {prof['kind']} · farklı {prof['distinct']}")
    if v["hidden"]:
        out(f"Değerler gösterilmez: {v['hidden']}. Yalnız şekiller aşağıda.")
    elif v["distribution_only"]:
        out("Dağılım (örneklem): " + (" · ".join(f"{q} {_fmt_q(x)}" for q, x in v["quantiles"].items())
                                      if v["quantiles"] else "hesaplanamadı (örneklem < 10)"))
        out("  (tarih / sürekli sayı: değer listesi yerine yüzdelikler; liste için --list)")
    else:
        out("Gösterim: " + (f"yalnız ≥ {k} farklı hastada geçen değerler (hasta anahtarı: {pk})" if pk else
                            f"yalnız ≥ {k} satırda geçen değerler (hasta anahtarı bulunamadı; --patient-col SUTUN)"))
        out.table(v["values"].rename(columns={"v": "değer", "n": "satır", "np": "hasta"}), a.top)
        rs, rt = v["rest_small"], v["rest_top"]
        if rt["values"]:
            out(f"  + ilk {a.top} dışında {rt['values']} değer ({sdc.fmt_count(rt['rows'])} satır) — --top ile artır")
        if rs["values"]:
            out(f"  + {rs['values']} değer < {k} {'hasta' if pk else 'satır'} (toplam {sdc.fmt_count(rs['rows'])} satır) "
                "— gösterilmez")
        if v["truncated"]:
            out(f"  (en sık {explore.GROUP_ROWS} değer okundu; daha fazlası var)")
        if v["quantiles"]:
            out("Dağılım (örneklem): " + " · ".join(f"{q} {_fmt_q(x)}" for q, x in v["quantiles"].items()))
    out("Şekiller (örneklem, %):")
    out.table(v["shapes"].rename(columns={"shape": "şekil", "pct": "%"}), 10)
    return 0


def cmd_find(a, out: Block, run) -> int:
    from sandbox.io import explore

    conn, target = connect(a)
    try:
        tb, cl = explore.find(conn, a.text, a.all)
    finally:
        conn.close()
    out(f"{target} — adında '{a.text}' geçen: {len(tb)} tablo / view, {len(cl)} sütun")
    if len(tb):
        out("Tablolar:")
        out.table(tb.rename(columns={"schema": "şema", "table": "tablo", "type": "tür"}), a.max_rows)
    if len(cl):
        out("Sütunlar:")
        out.table(cl.rename(columns={"schema": "şema", "table": "tablo", "column": "sütun", "type": "tip"}), a.max_rows)
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
    out(f"Sorgu: {a.sql[:300]}")
    out(f"Satır sayısı: {sdc.fmt_count(n)}")
    return 0


def cmd_mapping(a, out: Block, run) -> int:
    from sandbox.io.adapters import nabidh

    conn, target = connect(a)
    try:
        res = ce.check_mapping(conn, a.cohorts or None)
    finally:
        conn.close()
    out(f"{target} — adapter eşlemesi (src/sandbox/io/adapters/nabidh.py)")
    out("IRIS_COHORTS = " + json.dumps(nabidh.IRIS_COHORTS, ensure_ascii=False))
    print_results(out, res)
    bad = [x for x in res if x.status in (WARN, FAIL)]
    out(f"Özet: {sum(x.status == PASS for x in res)} PASS · {len(bad)} eksik"
        + (" → bu bloğu gönder: SOURCES / IRIS_COHORTS güncellenip push edilir → git pull → mapping tekrar" if bad else
           f" → sıradaki: {CMD} run ingest --cohorts c1 c2"))
    return 1 if bad else 0


# --------------------------------------------------------------------------
# Faz 1 / Faz 2 adımları ve çıktılar
# --------------------------------------------------------------------------
def safe_table(df):
    """Bloğa basılacak çıktı tablosu: hasta anahtarı sütunu varsa reddeder; sayım sütunlarında < 10 bastırır."""
    from sandbox import sdc
    from sandbox.io import explore

    bad = [c for c in df.columns if explore.patient_key([c])]
    if bad:
        raise ValueError(f"hasta düzeyi olabilir (sütun {bad}) — basılmaz")
    cols = [c for c in df.columns if _COUNTISH.search(str(c)) and not _NOT_COUNT.search(str(c))]
    return sdc.suppress_small_counts(df, cols) if cols else df


def framework_pivot(df):
    """nb00/framework_match.csv (kohort × grup, uzun) → grup başına kohort sütunlarında hasta %'si.
    Sayımı < 10 olan hücrede % de gösterilmez (yüzde × N ile sayım geri hesaplanmasın)."""
    small = df["patients_with_any"].astype(str).str.startswith("<")
    pct = df["pct_patients"].astype(object).where(~small, "<10 hasta")
    wide = df.assign(pct=pct).pivot_table(index=["domain", "group"], columns="cohort", values="pct", aggfunc="first")
    wide.columns.name = None
    return wide.reset_index()


def failure_lines(lines: list[str]) -> list[str]:
    """Hata özeti: traceback'in son 'File …' satırı + son iki dolu satır."""
    out = []
    tb = [ln.strip() for ln in lines if ln.strip().startswith('File "')]
    if tb:
        out.append("Yer: " + tb[-1].replace(str(REPO_ROOT), ".")[:200])
    tail = [ln.strip() for ln in lines if ln.strip()][-(1 if tb else 2):]
    out += [f"Hata: {ln[:240]}" for ln in tail]
    out.append("(Hata satırında hasta değeri olmadığını kontrol et; varsa o satırı kopyalama.)")
    return out


# İlaç → ATC özeti (ingest value_counts, kaynak "medications"): (alan, en çok satır, küçük değeri gizle).
# Kod / ad listelerinde < 10 satırda geçen değer basılmaz; sayımlar dosyada zaten bastırılmış.
MED_FIELDS = [
    ("drug → ATC method", 20, False), ("rows dropped: no study drug class", 1, False),
    ("combination products (rows → several ATC rows)", 1, False), ("ATC (3 chars) after mapping", 20, False),
    ("drug code not ATC/DDC", 10, True), ("ATC ← drug_name (name match)", 15, True),
    ("drug_name without study drug class", 15, True),
]


def medication_summary(v):
    import pandas as pd

    v = v[v["source"].eq("medications")]
    parts = []
    for field, top, hide_small in MED_FIELDS:
        x = v[v["field"].eq(field)]
        if hide_small:
            x = x[~x["n_rows"].astype(str).str.startswith("<")]
        parts.append(x.head(top))
    return pd.concat(parts)[["field", "value", "n_rows"]] if parts else v


def summary_ingest(d: Path, out: Block, a) -> None:
    import pandas as pd
    from sandbox import sdc

    for f in sorted((d / "ingest").glob("*_summary.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        c = f.name.split("_", 1)[0]
        out(f"== {c.upper()}: {sdc.fmt_count(s.get('n_patients'))} hasta · şema ERROR {s.get('schema_errors')} / "
            f"WARN {s.get('schema_warnings')} · eşlenemeyen değer satırı {sdc.fmt_count(s.get('unmapped_value_rows'))}")
        out("   satır: " + ", ".join(f"{t}={sdc.fmt_count(n)}" for t, n in (s.get("rows") or {}).items()))
        for name, src in (s.get("sources") or {}).items():
            extra = [f"{k}={sdc.fmt_count(v)}" for k, v in src.items()
                     if k.startswith(("unparseable_", "filtered_out_by_")) and v]
            extra += [f"{k}={v}" for k, v in src.items() if k.startswith("absent") and v]
            extra += [f"{k}: {v}" for k, v in src.items() if k.startswith("filtered_out_values_") and v]
            if src.get("error"):
                extra.append(str(src["error"])[:120])
            out(f"   {name:16s} {str(src.get('status', '?')):18s} okunan={sdc.fmt_count(src.get('rows_read', '-'))} "
                + " ".join(extra))
        val = d / "ingest" / f"{c}_validation.csv"
        if val.is_file():
            v = pd.read_csv(val)
            v = v[v["severity"] != "INFO"]
            if len(v):
                out("   şema kontrolü (INFO dışı):")
                out.table(safe_table(v), a.max_rows)
        vc = d / "ingest" / f"{c}_value_counts.csv"
        if vc.is_file():
            v_all = pd.read_csv(vc, dtype=str)
            v = v_all[v_all["value"].str.contains("unmapped", na=False)]
            if len(v):
                out("   eşlenemeyen değerler (adapter sözlüklerine eklenecek; < 10 bastırılmış):")
                out.table(v, a.max_rows)
            m = medication_summary(v_all)
            if len(m):
                out("   ilaç → ATC (DDC kodu / ilaç adı; kod ve ad listelerinde < 10 satırlık değer yok):")
                out.table(m, a.max_rows)


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
            if cols:
                df = df[[c for c in cols if c in df.columns]]
            out(f"-- {rel} ({len(df)} satır)")
            out.table(safe_table(df), a.max_rows)
    return show


SUMMARIES = {"ingest": summary_ingest, **{s: summary_tables(s) for s in SUMMARY_TABLES}}


def cmd_run(a, out: Block, run) -> int:
    from sandbox.config import DATA_DIR, OUTPUT_DIR

    cmd = [sys.executable, STEPS[a.step][0]]
    if a.step == "ingest":
        cmd += ["--source", a.source]
        if a.snapshot:
            snap = DATA_DIR / f"{a.source.removesuffix('_iris')}_iris" / "raw"     # ingest'in snapshot yeri
            cmd += ["--raw-root", str(snap.relative_to(REPO_ROOT))]
        else:
            cmd += ["--input", "iris"] + (["--iris-sqlite", str(a.iris_sqlite)] if a.iris_sqlite else [])
        if a.cohorts:
            cmd += ["--cohorts", *a.cohorts]
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "SANDBOX_SOURCE": a.source}
    if a.bootstrap_reps:
        env["SANDBOX_BOOTSTRAP_REPS"] = str(a.bootstrap_reps)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in OUTPUT_DIR.iterdir()}
    print(f"Çalışıyor: SANDBOX_SOURCE={a.source} python {' '.join(cmd[1:])}\n"
          "(aşağıdaki ekran çıktısı enclave içinde kalır; kopyalanacak özet en sonda)", flush=True)
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
        run.register_output(log, f"run {a.step} tam ekran çıktısı (enclave içinde kalır)")
    new = sorted(n for n in {p.name for p in OUTPUT_DIR.iterdir()} - before if not (run and n == run.run_id))
    out(f"Adım: run {a.step} · kaynak {a.source} · çıkış kodu {rc} · {time.time() - t0:.0f} sn")
    found = []
    for n in new:
        m = OUTPUT_DIR / n / "run_manifest.json"
        if m.is_file():
            d = json.loads(m.read_text(encoding="utf-8"))
            found.append(OUTPUT_DIR / n)
            out(f"Run: {n} · durum: {d.get('status')} · {len(d.get('outputs', []))} çıktı")
    if not found:
        out("Run kaydı bulunamadı (script audit açmadan durdu)")
    if rc != 0:
        for ln in failure_lines(lines):
            out(ln)
    for d in found:
        out()
        SUMMARIES[a.step](d, out, a)
    if run:
        out(f"Tam ekran çıktısı (enclave içinde): outputs/{run.run_id}/enclave/{a.step}.log")
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
        raise LookupError(f"run bulunamadı: {spec} (adım adı: {', '.join(STEPS)}, 'last' ya da run_id)")
    return cand[-1]


def cmd_show(a, out: Block, run) -> int:
    import pandas as pd

    d = resolve_run_dir(a.run)
    csvs = sorted(str(p.relative_to(d)) for p in d.rglob("*.csv"))
    if not a.path:
        out(f"{d.name} — {len(csvs)} tablo:")
        for c in csvs:
            out(f"  {c}")
        out(f"Bas: {CMD} show {a.run} DOSYA")
        return 0
    f = (d / a.path).resolve()
    if not f.is_relative_to(d.resolve()) or not f.is_file():
        raise LookupError(f"{a.path} yok; {d.name} tabloları: {', '.join(csvs[:30])}")
    if f.suffix.lower() != ".csv":
        raise ValueError("yalnız .csv tablolar basılır")
    df = pd.read_csv(f)
    out(f"{d.name}/{a.path} — {len(df)} satır")
    out.table(safe_table(df), a.max_rows)
    return 0


def cmd_last(a) -> int:
    from sandbox.config import OUTPUT_DIR

    blocks = sorted(OUTPUT_DIR.glob("*/enclave/block.txt"))
    if not blocks:
        print("Kayıtlı blok yok")
        return 1
    print(blocks[-1].read_text(encoding="utf-8"), end="")
    return 0


HANDLERS = {"req": cmd_req, "iris-setup": cmd_iris_setup, "schemas": cmd_schemas, "tables": cmd_tables,
            "columns": cmd_columns, "values": cmd_values, "find": cmd_find, "count": cmd_count,
            "mapping": cmd_mapping, "run": cmd_run, "show": cmd_show}


# --------------------------------------------------------------------------
# Komut satırı
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--iris-sqlite", type=Path, default=None,
                        help="prova: IRIS yerine <dizin>/<kohort>.sqlite (tools/make_nabidh_dryrun.py)")
    common.add_argument("--max-rows", type=int, default=60, help="tablolarda en fazla satır (varsayılan 60)")
    ap = argparse.ArgumentParser(prog="enclave.sh", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 description="Enclave terminal aracı — rehber: docs/enclave_terminal.md",
                                 epilog="Sonuç '----8<---- KOPYALA BAŞ' ile '----8<---- KOPYALA SON' arasında basılır.")
    sub = ap.add_subparsers(dest="cmd", metavar="KOMUT")

    p = sub.add_parser("req", parents=[common], help="VM gereksinimi: R1 … R9 ya da all")
    p.add_argument("ids", nargs="+", metavar="R", help="R1 … R9 (birkaç tane olabilir) ya da all")
    p.add_argument("--quick", action="store_true", help="R5: unit testleri ve pip check'i atla")

    p = sub.add_parser("iris-setup", help="~/.nabidh_iris: IRIS bağlantı dizesi + kullanıcı (şifre yazılmaz)")
    p.add_argument("--namespace", help="DHA'nın verdiği namespace (host/port varsayılan)")
    p.add_argument("--url", help="tam dize: jdbc:IRIS://host:port/NAMESPACE (ör. host yerine IP)")
    p.add_argument("--user", help="salt-okuma IRIS kullanıcısı")
    p.add_argument("--host", default=DEFAULT_IRIS_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_IRIS_PORT)
    p.add_argument("--yes", action="store_true", help="dosya varsa sormadan güncelle")

    p = sub.add_parser("schemas", parents=[common], help="namespace'teki şemalar (tablo / view sayısı)")
    p.add_argument("--all", action="store_true", help="sistem şemalarını da göster")
    p.add_argument("--like", help="adında geçen metin")

    p = sub.add_parser("tables", parents=[common], help="bir şemanın tabloları + satır sayıları")
    p.add_argument("schema", metavar="SEMA", help="şema adı ya da kohort: c1 / c2 / c3")
    p.add_argument("--like", help="tablo adında geçen metin")
    p.add_argument("--no-count", action="store_true", help="satır saymadan (büyük şemada hızlı)")

    p = sub.add_parser("columns", parents=[common], help="tablonun sütunları: tip, doluluk, şekil, tür")
    p.add_argument("table", metavar="SEMA.TABLO", help="ör. c1.Patient (kohort → şema) ya da ŞEMA.Patient")
    p.add_argument("--sample", type=int, default=5000, help="profil örneklemi (ilk N satır)")
    p.add_argument("--where", help="SQL koşulu (ör. \"PatientType = 'C1'\")")

    p = sub.add_parser("values", parents=[common], help="bir sütunun değer dağılımı (≥ 10 hasta)")
    p.add_argument("table", metavar="SEMA.TABLO", help="ör. c1.Patient (kohort → şema) ya da ŞEMA.Patient")
    p.add_argument("column", metavar="SUTUN")
    p.add_argument("--top", type=int, default=30)
    p.add_argument("--where", help="SQL koşulu")
    p.add_argument("--patient-col", default="auto", help="hasta anahtarı sütunu (auto / SUTUN / none)")
    p.add_argument("--sample", type=int, default=5000)
    p.add_argument("--list", action="store_true", help="tarih / sürekli sayıda da değer listesi (≥ 10 hasta kuralıyla)")

    p = sub.add_parser("find", parents=[common], help="adında metin geçen tablo ve sütunlar")
    p.add_argument("text", metavar="METIN")
    p.add_argument("--all", action="store_true", help="sistem şemalarında da ara")

    p = sub.add_parser("count", parents=[common], help="bir SELECT'in satır sayısı (satırlar okunmaz)")
    p.add_argument("sql", metavar='"SELECT ..."')

    p = sub.add_parser("mapping", parents=[common], help="adapter SOURCES / IRIS_COHORTS IRIS'te tutuyor mu")
    p.add_argument("cohorts", nargs="*", choices=["c1", "c2", "c3"], metavar="KOHORT")

    p = sub.add_parser("run", parents=[common], help="adım çalıştır: ingest, nb0, nb1, nb2, kpi")
    p.add_argument("step", choices=list(STEPS))
    p.add_argument("--cohorts", nargs="+", choices=["c1", "c2", "c3"], help="ingest: kohortlar")
    p.add_argument("--source", default="nabidh", help="SANDBOX_SOURCE / ingest --source (varsayılan nabidh)")
    p.add_argument("--snapshot", action="store_true", help="ingest: IRIS'e gitmeden son snapshot'tan")
    p.add_argument("--bootstrap-reps", type=int, default=None, help="nb2: SANDBOX_BOOTSTRAP_REPS")

    p = sub.add_parser("show", parents=[common], help="bir run'ın çıktı tablosunu bas (sayımlar bastırılmış)")
    p.add_argument("run", metavar="RUN", help="adım adı (ingest, nb0, nb1, nb2, kpi), last ya da run_id")
    p.add_argument("path", nargs="?", metavar="DOSYA", help="ör. nb01/score_summary.csv (boş: listele)")

    sub.add_parser("last", help="son KOPYALA bloğunu yeniden bas")
    sub.add_parser("help", help="bu yardım")
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
    import sandbox  # noqa: F401  (git dışı .env'i ortama yükler: SANDBOX_SOURCE, NABIDH_IRIS_PASSWORD …)
    for attr in ("table", "schema"):                 # c1.Patient → <C1 şeması>.Patient
        if getattr(a, attr, None):
            setattr(a, attr, cohort_alias(getattr(a, attr)))
    if a.cmd == "req":
        ids = [x.upper() for x in a.ids]
        a.ids = list(REQS) if "ALL" in ids else ids
        unknown = [x for x in a.ids if x not in REQS]
        if unknown:
            ap.error(f"bilinmeyen gereksinim: {', '.join(unknown)} (R1 … R9 ya da all)")
    if needs_password(a):
        ensure_password(a)
    run = open_run(a.cmd)
    utc = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    argv = safe_argv(argv)
    shown = shlex.join(argv)
    out = Block(f"{MARK} KOPYALA BAŞ | enclave {shown[:120]}{'...' if len(shown) > 120 else ''} | {utc} | "
                f"commit {commit_label()} | python {platform.python_version()} | {run.run_id if run else 'audit yok'} "
                f"{MARK}")
    try:
        rc = HANDLERS[a.cmd](a, out, run)
    except KeyboardInterrupt:
        out("İptal edildi (Ctrl+C)")
        rc = 130
    except Exception as e:
        out(f"HATA: {type(e).__name__}: {str(e)[:500]}")
        rc = 1
    out.close()
    finish_run(run, out, rc, argv)
    return rc


if __name__ == "__main__":
    sys.exit(main())
