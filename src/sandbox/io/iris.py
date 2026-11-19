"""InterSystems IRIS connection — DHA keeps NABIDH data in IRIS (connection: jdbc:IRIS://host:port/NAMESPACE).

This module is the only exception to rule 2: the driver (`intersystems-irispython`, fallback `pyodbc`) is loaded
only here and only when connecting (lazy import); tests and analysis code run without a driver. The connection
goes to IRIS inside DHA and is opened for SELECT only (`assert_select`).

Connection details (in order of precedence): function argument → environment variable (including the untracked
`.env` at the repo root; envfile.py) → credentials file (OUTSIDE the repo;
default ~/.nabidh_iris, `KEY=VALUE` lines, `chmod 600`) → password prompt (terminal, IntelliJ run configuration
with 'Emulate terminal' on, Jupyter; see `can_prompt`).
  NABIDH_IRIS_URL       jdbc:IRIS://host:port/NAMESPACE   (connection string given by DHA)
  NABIDH_IRIS_USER      read-only user
  NABIDH_IRIS_PASSWORD  password (environment, untracked .env or credentials file; never git, run configuration, audit)
  NABIDH_IRIS_ODBC      (fallback) full ODBC connection string → pyodbc; if set, URL/user are not used
  NABIDH_IRIS_CREDENTIALS  path of the credentials file (default ~/.nabidh_iris)
Only host:port/NAMESPACE and the user name go to the audit; the rest of the string (parameters) does not.

Dry run: `sqlite_standin` puts SQLite in place of IRIS (one file per cohort, ATTACHed under the IRIS schema name).
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
DEFAULT_PORT = 1972                     # IRIS superserver default; DHA's is in the string
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
    """jdbc:IRIS://host:port/NAMESPACE[/...][;...][?...] → (host, port, namespace). The rest is dropped."""
    m = _URL_RE.match(url.strip())
    if not m:
        raise ValueError("Cannot parse the IRIS connection string; expected: jdbc:IRIS://host:port/NAMESPACE")
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
    """Connection settings without the password (the form that may go to the audit)."""
    file = read_credentials_file()
    odbc = os.environ.get(ENV_ODBC) or file.get(ENV_ODBC)
    if odbc and not url:
        return {"driver": "pyodbc", "target": "ODBC (string not written to the audit)", "user": None}
    url = url or os.environ.get(ENV_URL) or file.get(ENV_URL)
    if not url:
        raise RuntimeError(f"No IRIS connection string: set the {ENV_URL} environment variable or {ENV_URL}=jdbc:IRIS://host:port/NAMESPACE "
                           f"in {credentials_file_path()}")
    user = user or os.environ.get(ENV_USER) or file.get(ENV_USER)
    if not user:
        raise RuntimeError(f"No IRIS user: {ENV_USER}")
    return {"driver": "intersystems-irispython", "target": str(parse_url(url)), "user": user, "_url": url}


def connect(url: str | None = None, user: str | None = None, password: str | None = None):
    """Returns a DB-API 2.0 connection (used for SELECT only)."""
    s = connection_settings(url, user)
    if s["driver"] == "pyodbc":
        try:
            import pyodbc  # noqa: PLC0415 — fallback path only
        except ImportError as e:
            raise RuntimeError("pyodbc is not installed (NABIDH_IRIS_ODBC is set)") from e
        return pyodbc.connect(os.environ.get(ENV_ODBC) or read_credentials_file()[ENV_ODBC], readonly=True)

    t = parse_url(s["_url"])
    password = password or os.environ.get(ENV_PASSWORD) or read_credentials_file().get(ENV_PASSWORD)
    if not password:
        where = f"{ENV_PASSWORD} environment variable or {credentials_file_path()}"
        if not can_prompt():
            raise RuntimeError(f"No IRIS password and cannot prompt for one (no terminal; 'Emulate terminal' off in the "
                               f"IntelliJ run configuration?): {where}")
        try:
            password = getpass.getpass(f"IRIS password ({s['user']}@{t}): ")
        except Exception as e:              # e.g. stdin closed in Jupyter (nbconvert / papermill)
            raise RuntimeError(f"Could not prompt for the IRIS password ({type(e).__name__}): {where}") from e
        if not password:
            raise RuntimeError(f"IRIS password is empty: {where}")
    try:
        fn = _driver_connect()
    except ImportError as e:
        raise RuntimeError("No IRIS driver: `pip install intersystems-irispython` "
                           "(or the pyodbc fallback via NABIDH_IRIS_ODBC)") from e
    if fn is None:
        raise RuntimeError("The installed `iris` module has no connect(); check the intersystems-irispython version")
    return fn(t.host, t.port, t.namespace, s["user"], password)


# Packages that write the same `iris/__init__.py` and replace the official driver (one overwrites the other, by install order).
# sqlalchemy-iris pulls in iris-embedded-python-wrapper: that is why it is not in the explore list.
CONFLICTING_DISTS = ("iris-embedded-python-wrapper", "scitools-iris")


def _driver_connect():
    """intersystems-irispython's DB-API 2.0 connect (`iris.dbapi`, apilevel 2.0); otherwise `iris.connect`."""
    import iris  # noqa: PLC0415 — intersystems-irispython (ImportError goes to the caller)

    try:
        import iris.dbapi as dbapi  # noqa: PLC0415
        fn = getattr(dbapi, "connect", None)
    except ImportError:
        fn = None
    return fn or getattr(iris, "connect", None)


def driver_status() -> list[dict]:
    """Installed IRIS drivers, without connecting: [{name, version, ok, detail, conflict}] (tools/check_environment.py)."""
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
        detail = "" if callable(fn) else "the `iris` module has no connect() (a different `iris` package?)"
        if conflicts:
            detail = (f"{', '.join(conflicts)} also installed: it overwrites iris/__init__.py and may run instead of the official driver "
                      f"→ uninstall it and `pip install --force-reinstall --no-deps intersystems-irispython`. " + detail)
        out.append({"name": "intersystems-irispython", "version": version("intersystems-irispython"),
                    "ok": callable(fn), "detail": detail.strip(), "conflict": bool(conflicts)})
    except ImportError as e:
        out.append({"name": "intersystems-irispython", "version": None, "ok": False, "detail": str(e),
                    "conflict": bool(conflicts)})
    try:
        import pyodbc  # noqa: PLC0415 — fallback path
        drivers = [d for d in pyodbc.drivers() if "intersystems" in d.lower() or "iris" in d.lower()]
        out.append({"name": "pyodbc", "version": version("pyodbc"), "ok": bool(drivers), "conflict": False,
                    "detail": f"ODBC drivers: {drivers}" if drivers else "no InterSystems ODBC driver registered"})
    except ImportError as e:
        out.append({"name": "pyodbc", "version": None, "ok": False, "detail": str(e), "conflict": False})
    return out


def tcp_check(host: str, port: int, timeout: float = 5.0) -> float:
    """Opens and closes a TCP connection to host:port; returns the time in ms (OSError → unreachable)."""
    import socket  # noqa: PLC0415
    import time  # noqa: PLC0415

    t0 = time.perf_counter()
    with socket.create_connection((host, port), timeout=timeout):
        pass
    return (time.perf_counter() - t0) * 1000


def resolve_host(host: str, port: int) -> list[str]:
    """IP addresses of host in DNS (socket.gaierror → does not resolve). An IP is returned as is."""
    import socket  # noqa: PLC0415

    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    return list(dict.fromkeys(i[4][0] for i in infos))


def credentials_file_path() -> Path:
    return Path(os.environ.get(ENV_CREDENTIALS) or DEFAULT_CREDENTIALS).expanduser()


def can_prompt() -> bool:
    """Can the password be prompted for interactively: a real terminal (including IntelliJ run configurations with
    'Emulate terminal' on) or a Jupyter kernel (ipykernel forwards getpass to the front end)."""
    try:
        tty = sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):     # closed / replaced stdin
        tty = False
    return tty or "ipykernel" in sys.modules


# --------------------------------------------------------------------------
# Query
# --------------------------------------------------------------------------
_COMMENT_RE = re.compile(r"(--[^\n]*|/\*.*?\*/)", re.DOTALL)


def assert_select(sql: str) -> str:
    """Allows a single SELECT / WITH statement only (no risk of writing to the DHA database)."""
    body = _COMMENT_RE.sub(" ", sql).strip().rstrip(";").strip()
    if not re.match(r"^(SELECT|WITH)\b", body, re.IGNORECASE) or ";" in body:
        raise ValueError(f"Only a single SELECT query is run: {sql[:80]!r}")
    return sql


def column_names(conn, table: str) -> list[str]:
    """Column names of a table, without reading rows (works in IRIS and SQLite)."""
    cur = conn.cursor()
    try:
        cur.execute(assert_select(f"SELECT * FROM {table} WHERE 1=0"))
        return [d[0] for d in cur.description]
    finally:
        cur.close()


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def fetch(conn, sql: str, fetch_rows: int = FETCH_ROWS) -> tuple[pd.DataFrame, str]:
    """Runs the query → (text table as from a raw file, CSV text of that table).

    Values are written to CSV and read back with the same reader: dates as ISO text, numbers as text, NULL → empty.
    So a table from IRIS and a raw file take exactly the same path through the adapter; the CSV text can be
    written to the snapshot file as is (same hash as the file).
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
    # dtype=object: an integer column with NULLs must not turn into float (8517006 must not become "8517006.0")
    return as_text_table(pd.DataFrame(rows, columns=cols, dtype=object))


def as_text_table(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """DataFrame → (text table as the raw-file reader would give, CSV text)."""
    from .adapters.synthetic import read_raw_csv_text  # noqa: PLC0415

    text = df.to_csv(index=False, lineterminator="\n")
    return read_raw_csv_text(text), text


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Dry run: SQLite in place of IRIS
# --------------------------------------------------------------------------
def write_sqlite_standin(path: Path, tables: dict[str, pd.DataFrame]) -> Path:
    """{table: df} → one SQLite file (all columns TEXT). For dry runs / tests only."""
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
    """{IRIS schema: sqlite file} → an in-memory connection with each file attached under that schema name.
    So `SELECT ... FROM NABIDH_C1.Patient` works as in IRIS."""
    con = sqlite3.connect(":memory:")
    for schema, path in schemas.items():
        if not Path(path).is_file():
            raise FileNotFoundError(path)
        con.execute("ATTACH DATABASE ? AS " + quote_ident(schema), (str(path),))
    return con
