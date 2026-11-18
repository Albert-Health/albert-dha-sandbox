"""InterSystems IRIS bağlantısı — NABIDH verisi DHA'da IRIS'te tutulur (bağlantı: jdbc:IRIS://host:port/NAMESPACE).

Kural 2'nin tek istisnası bu modüldür: sürücü (`intersystems-irispython`, yedek `pyodbc`) yalnızca burada ve
yalnızca bağlanırken (tembel import) yüklenir; testler ve analiz kodu sürücüsüz çalışır. Bağlantı DHA içindeki
IRIS'e, yalnızca SELECT için açılır (`assert_select`).

Bağlantı bilgisi (öncelik sırasıyla): fonksiyon argümanı → ortam değişkeni → kimlik dosyası (repo DIŞINDA;
varsayılan ~/.nabidh_iris, `KEY=VALUE` satırları, `chmod 600`) → şifre için sorulur (terminal, IntelliJ'de
'Emulate terminal' açık run configuration, Jupyter; bkz. `can_prompt`).
  NABIDH_IRIS_URL       jdbc:IRIS://host:port/NAMESPACE   (DHA'nın verdiği bağlantı dizesi)
  NABIDH_IRIS_USER      salt-okunur kullanıcı
  NABIDH_IRIS_PASSWORD  şifre (dosyaya ya da ortama; repoya, run configuration'a, audit'e asla)
  NABIDH_IRIS_ODBC      (yedek) tam ODBC bağlantı dizesi → pyodbc; verilirse URL/kullanıcı kullanılmaz
  NABIDH_IRIS_CREDENTIALS  kimlik dosyasının yolu (varsayılan ~/.nabidh_iris)
Audit'e yalnızca host:port/NAMESPACE ve kullanıcı adı yazılır; dizenin geri kalanı (parametreler) yazılmaz.

Prova: `sqlite_standin` IRIS'in yerine SQLite koyar (kohort başına bir dosya, IRIS şeması adıyla ATTACH).
"""
from __future__ import annotations

import getpass
import hashlib
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ENV_URL = "NABIDH_IRIS_URL"
ENV_USER = "NABIDH_IRIS_USER"
ENV_PASSWORD = "NABIDH_IRIS_PASSWORD"
ENV_ODBC = "NABIDH_IRIS_ODBC"
ENV_CREDENTIALS = "NABIDH_IRIS_CREDENTIALS"
DEFAULT_CREDENTIALS = Path.home() / ".nabidh_iris"
DEFAULT_PORT = 1972                     # IRIS superserver varsayılanı; DHA'nınki dizede yazar
FETCH_ROWS = 50_000


@dataclass(frozen=True)
class IrisTarget:
    host: str
    port: int
    namespace: str

    def __str__(self) -> str:
        return f"{self.host}:{self.port}/{self.namespace}"


_URL_RE = re.compile(r"^(?:jdbc:)?(?:iris://)?(?P<host>[^:/;?]+)(?::(?P<port>\d+))?/(?P<ns>[^/;?]+)",
                     re.IGNORECASE)


def parse_url(url: str) -> IrisTarget:
    """jdbc:IRIS://host:port/NAMESPACE[/...][;...][?...] → (host, port, namespace). Gerisi atılır."""
    m = _URL_RE.match(url.strip())
    if not m:
        raise ValueError("IRIS bağlantı dizesi çözülemedi; beklenen: jdbc:IRIS://host:port/NAMESPACE")
    return IrisTarget(m["host"], int(m["port"] or DEFAULT_PORT), m["ns"])


def read_credentials_file(path: Path | None = None) -> dict[str, str]:
    path = Path(path).expanduser() if path else credentials_file_path()
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def connection_settings(url: str | None = None, user: str | None = None) -> dict:
    """Şifre hariç bağlantı ayarları (audit'e yazılabilir hâli)."""
    file = read_credentials_file()
    odbc = os.environ.get(ENV_ODBC) or file.get(ENV_ODBC)
    if odbc and not url:
        return {"driver": "pyodbc", "target": "ODBC (dize audit'e yazılmaz)", "user": None}
    url = url or os.environ.get(ENV_URL) or file.get(ENV_URL)
    if not url:
        raise RuntimeError(f"IRIS bağlantı dizesi yok: {ENV_URL} ortam değişkeni ya da {credentials_file_path()} "
                           f"dosyasında {ENV_URL}=jdbc:IRIS://host:port/NAMESPACE")
    user = user or os.environ.get(ENV_USER) or file.get(ENV_USER)
    if not user:
        raise RuntimeError(f"IRIS kullanıcısı yok: {ENV_USER}")
    return {"driver": "intersystems-irispython", "target": str(parse_url(url)), "user": user, "_url": url}


def connect(url: str | None = None, user: str | None = None, password: str | None = None):
    """DB-API 2.0 bağlantısı döndürür (yalnızca SELECT için kullanılır)."""
    s = connection_settings(url, user)
    if s["driver"] == "pyodbc":
        try:
            import pyodbc  # noqa: PLC0415 — yalnız yedek yol
        except ImportError as e:
            raise RuntimeError("pyodbc kurulu değil (NABIDH_IRIS_ODBC verildi)") from e
        return pyodbc.connect(os.environ.get(ENV_ODBC) or read_credentials_file()[ENV_ODBC], readonly=True)

    t = parse_url(s["_url"])
    password = password or os.environ.get(ENV_PASSWORD) or read_credentials_file().get(ENV_PASSWORD)
    if not password:
        where = f"{ENV_PASSWORD} ortam değişkeni ya da {credentials_file_path()}"
        if not can_prompt():
            raise RuntimeError(f"IRIS şifresi yok ve sorulamıyor (terminal yok; IntelliJ run configuration'ında "
                               f"'Emulate terminal' kapalı?): {where}")
        try:
            password = getpass.getpass(f"IRIS şifresi ({s['user']}@{t}): ")
        except Exception as e:              # ör. Jupyter'de stdin kapalı (nbconvert / papermill)
            raise RuntimeError(f"IRIS şifresi sorulamadı ({type(e).__name__}): {where}") from e
        if not password:
            raise RuntimeError(f"IRIS şifresi boş: {where}")
    try:
        fn = _driver_connect()
    except ImportError as e:
        raise RuntimeError("IRIS sürücüsü yok: `pip install intersystems-irispython` "
                           "(ya da NABIDH_IRIS_ODBC ile pyodbc yedeği)") from e
    if fn is None:
        raise RuntimeError("Kurulu `iris` modülünde connect() yok; intersystems-irispython sürümünü kontrol et")
    return fn(t.host, t.port, t.namespace, s["user"], password)


# Aynı `iris/__init__.py`'yi yazan, resmi sürücünün yerine geçen paketler (kurulum sırasına göre biri ezer).
# sqlalchemy-iris, iris-embedded-python-wrapper'ı çeker: bu yüzden keşif listesinde yok.
CONFLICTING_DISTS = ("iris-embedded-python-wrapper", "scitools-iris")


def _driver_connect():
    """intersystems-irispython'ın DB-API 2.0 connect'i (`iris.dbapi`, apilevel 2.0); yoksa `iris.connect`."""
    import iris  # noqa: PLC0415 — intersystems-irispython (ImportError çağırana)

    try:
        import iris.dbapi as dbapi  # noqa: PLC0415
        fn = getattr(dbapi, "connect", None)
    except ImportError:
        fn = None
    return fn or getattr(iris, "connect", None)


def driver_status() -> list[dict]:
    """Kurulu IRIS sürücüleri, bağlanmadan: [{name, version, ok, detail, conflict}] (tools/check_environment.py)."""
    from importlib import metadata  # noqa: PLC0415

    def version(dist):
        try:
            return metadata.version(dist)
        except metadata.PackageNotFoundError:
            return None

    out = []
    conflicts = [d for d in CONFLICTING_DISTS if version(d)]
    try:
        fn = _driver_connect()
        detail = "" if callable(fn) else "`iris` modülünde connect() yok (başka bir `iris` paketi mi?)"
        if conflicts:
            detail = (f"{', '.join(conflicts)} de kurulu: iris/__init__.py'yi ezer, resmi sürücü yerine o çalışabilir "
                      f"→ kaldır ve `pip install --force-reinstall --no-deps intersystems-irispython`. " + detail)
        out.append({"name": "intersystems-irispython", "version": version("intersystems-irispython"),
                    "ok": callable(fn), "detail": detail.strip(), "conflict": bool(conflicts)})
    except ImportError as e:
        out.append({"name": "intersystems-irispython", "version": None, "ok": False, "detail": str(e),
                    "conflict": bool(conflicts)})
    try:
        import pyodbc  # noqa: PLC0415 — yedek yol
        drivers = [d for d in pyodbc.drivers() if "intersystems" in d.lower() or "iris" in d.lower()]
        out.append({"name": "pyodbc", "version": version("pyodbc"), "ok": bool(drivers), "conflict": False,
                    "detail": f"ODBC sürücüleri: {drivers}" if drivers else "InterSystems ODBC sürücüsü kayıtlı değil"})
    except ImportError as e:
        out.append({"name": "pyodbc", "version": None, "ok": False, "detail": str(e), "conflict": False})
    return out


def tcp_check(host: str, port: int, timeout: float = 5.0) -> float:
    """host:port'a TCP bağlantısı açıp kapatır; süreyi ms olarak döndürür (OSError → erişilemiyor)."""
    import socket  # noqa: PLC0415
    import time  # noqa: PLC0415

    t0 = time.perf_counter()
    with socket.create_connection((host, port), timeout=timeout):
        pass
    return (time.perf_counter() - t0) * 1000


def resolve_host(host: str, port: int) -> list[str]:
    """host'un DNS'teki IP adresleri (socket.gaierror → çözülmüyor). IP verilirse kendisi döner."""
    import socket  # noqa: PLC0415

    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    return list(dict.fromkeys(i[4][0] for i in infos))


def credentials_file_path() -> Path:
    return Path(os.environ.get(ENV_CREDENTIALS) or DEFAULT_CREDENTIALS).expanduser()


def can_prompt() -> bool:
    """Şifre etkileşimli sorulabilir mi: gerçek terminal (IntelliJ'de 'Emulate terminal' açık run configuration'lar
    dahil) ya da Jupyter kernel'i (ipykernel getpass'i ön yüze iletir)."""
    try:
        tty = sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):     # kapalı / değiştirilmiş stdin
        tty = False
    return tty or "ipykernel" in sys.modules


# --------------------------------------------------------------------------
# Sorgu
# --------------------------------------------------------------------------
_COMMENT_RE = re.compile(r"(--[^\n]*|/\*.*?\*/)", re.DOTALL)


def assert_select(sql: str) -> str:
    """Yalnızca tek bir SELECT / WITH ifadesine izin verir (DHA veritabanına yazma riski yok)."""
    body = _COMMENT_RE.sub(" ", sql).strip().rstrip(";").strip()
    if not re.match(r"^(SELECT|WITH)\b", body, re.IGNORECASE) or ";" in body:
        raise ValueError(f"Yalnızca tek bir SELECT sorgusu çalıştırılır: {sql[:80]!r}")
    return sql


def column_names(conn, table: str) -> list[str]:
    """Tablonun sütun adları, satır okumadan (IRIS ve SQLite'ta çalışır)."""
    cur = conn.cursor()
    try:
        cur.execute(assert_select(f"SELECT * FROM {table} WHERE 1=0"))
        return [d[0] for d in cur.description]
    finally:
        cur.close()


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def fetch(conn, sql: str, fetch_rows: int = FETCH_ROWS) -> tuple[pd.DataFrame, str]:
    """Sorguyu çalıştırır → (ham dosyadaki gibi metin tablosu, o tablonun CSV metni).

    Değerler CSV'ye yazılıp aynı okuyucuyla geri okunur: tarihler ISO metni, sayılar metin, NULL → boş.
    Böylece IRIS'ten gelen tablo ile ham dosya adapter'da birebir aynı yoldan geçer; CSV metni olduğu
    gibi snapshot dosyasına yazılabilir (hash'i dosyanınkiyle aynı).
    """
    cur = conn.cursor()
    try:
        cur.execute(assert_select(sql))
        cols = [d[0] for d in cur.description]
        rows: list[tuple] = []
        while True:
            batch = cur.fetchmany(fetch_rows)
            if not batch:
                break
            rows.extend(tuple(r) for r in batch)
    finally:
        cur.close()
    # dtype=object: NULL'lu tamsayı sütunu float'a dönmesin (8517006 → "8517006.0" olmasın)
    return as_text_table(pd.DataFrame(rows, columns=cols, dtype=object))


def as_text_table(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """DataFrame → (ham dosya okuyucusunun vereceği metin tablosu, CSV metni)."""
    from .adapters.synthetic import read_raw_csv_text  # noqa: PLC0415

    text = df.to_csv(index=False, lineterminator="\n")
    return read_raw_csv_text(text), text


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Prova: IRIS yerine SQLite
# --------------------------------------------------------------------------
def write_sqlite_standin(path: Path, tables: dict[str, pd.DataFrame]) -> Path:
    """{tablo: df} → tek SQLite dosyası (tüm sütunlar TEXT). Yalnız prova / test içindir."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        for name, df in tables.items():
            cols = ", ".join(f"{quote_ident(c)} TEXT" for c in df.columns)
            con.execute(f"CREATE TABLE {quote_ident(name)} ({cols})")
            vals = df.astype(object).where(df.notna(), None).itertuples(index=False, name=None)
            con.executemany(f"INSERT INTO {quote_ident(name)} VALUES ({', '.join('?' * len(df.columns))})",
                            [tuple(None if v is None else str(v) for v in r) for r in vals])
        con.commit()
    finally:
        con.close()
    return path


def sqlite_standin(schemas: dict[str, Path]) -> sqlite3.Connection:
    """{IRIS şeması: sqlite dosyası} → her dosya o şema adıyla bağlı bir bellek-içi bağlantı.
    Böylece `SELECT ... FROM NABIDH_C1.Patient` IRIS'teki gibi çalışır."""
    con = sqlite3.connect(":memory:")
    for schema, path in schemas.items():
        if not Path(path).is_file():
            raise FileNotFoundError(path)
        con.execute("ATTACH DATABASE ? AS " + quote_ident(schema), (str(path),))
    return con
