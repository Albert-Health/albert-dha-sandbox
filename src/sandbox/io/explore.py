"""IRIS'i terminalden keşif: şemalar, tablolar, sütunlar, değer dağılımları (IntelliJ Database aracı yokken).

Amaç: adapter eşlemesi (io/adapters/nabidh.py → SOURCES, IRIS_COHORTS) için gereken bilgiyi grafik arayüz
olmadan, terminale basmak. Basılan her şey meta veri ya da özettir ve enclave dışına kopyalanabilir: şema /
tablo / sütun adları, tipler, satır sayıları, doluluk, değer "şekli" (2023-01-05 → 9999-99-99) ve küçük
hücreleri gizlenmiş değer sayımları. Hasta düzeyi değer basılmaz:
- kimlik / ad / doğum tarihi / iletişim benzeri adlı sütunlarda (`is_sensitive`) ve neredeyse her satırı farklı
  (kimlik gibi) sütunlarda değerin kendisi yerine yalnız şekli gösterilir (`hidden_reason`);
- bir değer ancak ≥ small_cell_threshold (10) farklı hastada geçiyorsa gösterilir (hasta anahtarı bulunamazsa
  satır sayısına bakılır); gerisi tek satırda toplanır.

Bağlantıyı io/iris.py açar; bu modül sürücü import etmez, DB-API kullanır ve yalnız SELECT gönderir
(`iris.assert_select`). Katalog: IRIS'te INFORMATION_SCHEMA, provada SQLite stand-in (`iris.sqlite_standin`).
"""
from __future__ import annotations

import difflib
import re
import sqlite3
import warnings

import pandas as pd

from ..config import PARAMS
from . import iris

SAMPLE_ROWS = 5000                 # sütun profili / şekiller bu kadar satırlık örneklemden (ilk satırlar)
GROUP_ROWS = 1000                  # değer sayımında GROUP BY sonucundan en fazla bu kadar değer okunur
VALUE_MAX_LEN = 60
SYSTEM_SCHEMAS = {"INFORMATION_SCHEMA"}
CHAR_TYPES = {"varchar", "char", "nvarchar", "nchar", "character varying", "string", "text"}
STREAM_TYPES = {"longvarchar", "longvarbinary", "varbinary", "binary", "blob", "clob"}   # gruplanamaz


def threshold() -> int:
    return int(PARAMS["small_cell_threshold"])


# --------------------------------------------------------------------------
# Sorgu yardımcıları
# --------------------------------------------------------------------------
def dialect(conn) -> str:
    return "sqlite" if isinstance(conn, sqlite3.Connection) else "iris"


def lit(s) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def ident(schema: str, table: str) -> str:
    return f"{iris.quote_ident(schema)}.{iris.quote_ident(table)}"


def limited(conn, body: str, n: int) -> str:
    """'SELECT <body>' + satır sınırı: IRIS'te TOP n, SQLite'ta LIMIT n (body ORDER BY içerebilir)."""
    if dialect(conn) == "iris":
        return f"SELECT TOP {int(n)} {body}"
    return f"SELECT {body} LIMIT {int(n)}"


def run_query(conn, sql: str, lower: bool = True) -> pd.DataFrame:
    """Tek SELECT → DataFrame (dtype=object). lower: sütun adları küçük harfe (katalog sorguları için)."""
    cur = conn.cursor()
    try:
        cur.execute(iris.assert_select(sql))
        cols = [str(d[0]) for d in cur.description]
        rows = [tuple(r) for r in cur.fetchall()]
    finally:
        cur.close()
    return pd.DataFrame(rows, columns=[c.lower() for c in cols] if lower else cols, dtype=object)


def where_clause(where: str | None) -> str:
    return f" WHERE {where}" if where else ""


# --------------------------------------------------------------------------
# Katalog
# --------------------------------------------------------------------------
def is_system_schema(name: str) -> bool:
    return str(name).startswith("%") or str(name).upper() in SYSTEM_SCHEMAS


def _drop_system(df: pd.DataFrame) -> pd.DataFrame:
    """Sistem şemalarını atar (boş tabloda da sütunlar korunur)."""
    return df.loc[~df["schema"].map(is_system_schema).astype(bool)]


def _sqlite_schemas(conn) -> list[str]:
    return [s for s in run_query(conn, "SELECT name FROM pragma_database_list")["name"] if s != "temp"]


def list_schemas(conn, include_system: bool = False, like: str | None = None) -> pd.DataFrame:
    """→ schema, tables, views. Sistem şemaları (% ile başlayanlar, INFORMATION_SCHEMA) varsayılan gizli."""
    if dialect(conn) == "sqlite":
        rows = []
        for s in _sqlite_schemas(conn):
            t = run_query(conn, f"SELECT type, COUNT(*) AS n FROM {iris.quote_ident(s)}.sqlite_master "
                                "WHERE type IN ('table', 'view') GROUP BY type")
            rows += [(s, typ, n) for typ, n in t.itertuples(index=False)]
        df = pd.DataFrame(rows, columns=["schema", "type", "n"])
    else:
        df = run_query(conn, "SELECT TABLE_SCHEMA AS schema_name, TABLE_TYPE AS table_type, COUNT(*) AS n "
                             "FROM INFORMATION_SCHEMA.TABLES GROUP BY TABLE_SCHEMA, TABLE_TYPE")
        df.columns = ["schema", "type", "n"]
    if df.empty:
        return pd.DataFrame(columns=["schema", "tables", "views"])
    df["n"] = pd.to_numeric(df["n"]).astype(int)
    df["kind"] = ["views" if "VIEW" in str(t).upper() else "tables" for t in df["type"]]
    out = df.pivot_table(index="schema", columns="kind", values="n", aggfunc="sum", fill_value=0)
    for c in ("tables", "views"):
        if c not in out.columns:
            out[c] = 0
    out = out[["tables", "views"]].reset_index()
    out.columns.name = None
    if not include_system:
        out = _drop_system(out)
    if like:
        out = out.loc[out["schema"].astype(str).str.contains(like, case=False, regex=False)]
    out = out.loc[(out["tables"] + out["views"]) > 0]
    return out.sort_values("schema", key=lambda s: s.astype(str).str.upper()).reset_index(drop=True)


def list_tables(conn, schema: str) -> pd.DataFrame:
    """→ schema, table, type (şema adı büyük/küçük harf duyarsız; katalogdaki yazımla döner)."""
    if dialect(conn) == "sqlite":
        names = {s.upper(): s for s in _sqlite_schemas(conn)}
        s = names.get(schema.upper())
        if s is None:
            return pd.DataFrame(columns=["schema", "table", "type"])
        df = run_query(conn, f"SELECT name, type FROM {iris.quote_ident(s)}.sqlite_master "
                             "WHERE type IN ('table', 'view') ORDER BY name")
        df.insert(0, "schema", s)
    else:
        df = run_query(conn, "SELECT TABLE_SCHEMA AS schema_name, TABLE_NAME AS table_name, TABLE_TYPE AS table_type "
                             f"FROM INFORMATION_SCHEMA.TABLES WHERE UPPER(TABLE_SCHEMA) = {lit(schema.upper())} "
                             "ORDER BY TABLE_NAME")
    df.columns = ["schema", "table", "type"]
    return df


def list_columns(conn, schema: str, table: str) -> pd.DataFrame:
    """→ column, type, nullable (tablodaki sırayla). Katalogda görünmüyorsa adlar `WHERE 1=0` sorgusundan."""
    if dialect(conn) == "sqlite":
        raw = run_query(conn, f'SELECT name, type, "notnull" AS nn FROM pragma_table_info({lit(table)}, {lit(schema)}) '
                              "ORDER BY cid")
        df = pd.DataFrame({"column": raw["name"], "type": raw["type"],
                           "nullable": ["NO" if int(v) else "YES" for v in raw["nn"]]})
    else:
        df = run_query(conn, "SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type, IS_NULLABLE AS is_nullable "
                             "FROM INFORMATION_SCHEMA.COLUMNS "
                             f"WHERE UPPER(TABLE_SCHEMA) = {lit(schema.upper())} "
                             f"AND UPPER(TABLE_NAME) = {lit(table.upper())} ORDER BY ORDINAL_POSITION")
        df.columns = ["column", "type", "nullable"]
    if df.empty:
        names = iris.column_names(conn, ident(schema, table))
        df = pd.DataFrame({"column": names, "type": "?", "nullable": "?"})
    df["type"] = df["type"].astype(str).str.lower()
    return df.reset_index(drop=True)


def _close(name: str, candidates) -> list[str]:
    by_upper = {str(c).upper(): str(c) for c in candidates}
    return [by_upper[m] for m in difflib.get_close_matches(name.upper(), list(by_upper), n=5, cutoff=0.5)]


def resolve_table(conn, name: str) -> tuple[str, str]:
    """'ŞEMA.Tablo' (büyük/küçük harf duyarsız) → katalogdaki (şema, tablo). Yoksa yakın adlarla LookupError."""
    parts = [p.strip().strip('"') for p in str(name).split(".")]
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"Tablo ŞEMA.Tablo biçiminde yazılmalı (ör. HSAA.Patient): {name!r}")
    schema, table = parts
    t = list_tables(conn, schema)
    if t.empty:
        close = _close(schema, list_schemas(conn, include_system=True)["schema"])
        raise LookupError(f"Şema yok ya da tablosu görünmüyor: {schema}"
                          + (f" — yakın adlar: {', '.join(close)}" if close else " — `schemas` ile listele"))
    hit = t[t["table"].astype(str).str.upper() == table.upper()]
    if hit.empty:
        close = _close(table, t["table"])
        raise LookupError(f"{schema} şemasında tablo yok: {table}"
                          + (f" — yakın adlar: {', '.join(close)}" if close else f" — `tables {schema}` ile listele"))
    return str(hit["schema"].iloc[0]), str(hit["table"].iloc[0])


def resolve_column(columns: pd.DataFrame, name: str) -> pd.Series:
    hit = columns[columns["column"].astype(str).str.upper() == str(name).upper()]
    if hit.empty:
        close = _close(name, columns["column"])
        raise LookupError(f"Sütun yok: {name}" + (f" — yakın adlar: {', '.join(close)}" if close else
                                                   f" — sütunlar: {', '.join(map(str, columns['column'][:40]))}"))
    return hit.iloc[0]


def find(conn, text: str, include_system: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Adında `text` geçen tablolar ve sütunlar → (schema, table, type), (schema, table, column, type)."""
    if dialect(conn) == "sqlite":
        trows, crows = [], []
        for s in _sqlite_schemas(conn):
            for _, tb, typ in list_tables(conn, s).itertuples(index=False):
                if text.lower() in str(tb).lower():
                    trows.append((s, tb, typ))
                for col, ctyp, _ in list_columns(conn, s, tb).itertuples(index=False):
                    if text.lower() in str(col).lower():
                        crows.append((s, tb, col, ctyp))
        tables = pd.DataFrame(trows, columns=["schema", "table", "type"])
        cols = pd.DataFrame(crows, columns=["schema", "table", "column", "type"])
    else:
        pat = lit("%" + text.upper() + "%")
        tables = run_query(conn, "SELECT TABLE_SCHEMA AS s, TABLE_NAME AS t, TABLE_TYPE AS ty "
                                 f"FROM INFORMATION_SCHEMA.TABLES WHERE UPPER(TABLE_NAME) LIKE {pat}")
        tables.columns = ["schema", "table", "type"]
        cols = run_query(conn, "SELECT TABLE_SCHEMA AS s, TABLE_NAME AS t, COLUMN_NAME AS c, DATA_TYPE AS ty "
                               f"FROM INFORMATION_SCHEMA.COLUMNS WHERE UPPER(COLUMN_NAME) LIKE {pat}")
        cols.columns = ["schema", "table", "column", "type"]
    if not include_system:
        tables, cols = _drop_system(tables), _drop_system(cols)
    key = ["schema", "table"]
    return (tables.sort_values(key).reset_index(drop=True),
            cols.sort_values([*key, "column"]).reset_index(drop=True))


def count_rows(conn, schema: str, table: str, where: str | None = None) -> int:
    return int(run_query(conn, f"SELECT COUNT(*) AS n FROM {ident(schema, table)}{where_clause(where)}").iloc[0, 0])


def count_query(conn, sql: str) -> int:
    """Kullanıcının SELECT'inin satır sayısı: SELECT COUNT(*) FROM (<sql>) q — satırlar okunmaz."""
    body = iris.assert_select(sql).strip().rstrip(";").strip()
    return int(run_query(conn, f"SELECT COUNT(*) AS n FROM ({body}) q").iloc[0, 0])


def sample(conn, schema: str, table: str, n: int = SAMPLE_ROWS, where: str | None = None,
           columns: list[str] | None = None) -> pd.DataFrame:
    """İlk n satır (sıralama yok: rastgele değil, yalnız biçim / doluluk ipucu için). Ekrana basılmaz."""
    cols = ", ".join(iris.quote_ident(c) for c in columns) if columns else "*"
    return run_query(conn, limited(conn, f"{cols} FROM {ident(schema, table)}{where_clause(where)}", n), lower=False)


# --------------------------------------------------------------------------
# Değer özetleri (hasta düzeyi değer basmadan)
# --------------------------------------------------------------------------
def to_text(v) -> str | None:
    """Sürücüden gelen değer → metin (boş / NULL → None). Tarih / sayı, ham CSV'deki gibi str()."""
    if v is None:
        return None
    if isinstance(v, float) and v != v:
        return None
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "<bytes>"
    s = str(v)
    return s if s.strip() else None


def shape(text: str, max_len: int = 24) -> str:
    """Değerin biçimi: rakam → 9 (tek tek), harf dizisi → a, boşluk dizisi → ' ', diğer karakterler aynen.
    2023-01-05 → 9999-99-99 · E11.9 → a99.9 · 'Never smoked' → 'a a' · 66841 → 99999."""
    out: list[str] = []
    for ch in str(text):
        c = "9" if ch.isdigit() else "a" if ch.isalpha() else " " if ch.isspace() else ch
        if c in ("a", " ") and out and out[-1] == c:
            continue
        out.append(c)
    s = "".join(out)
    return s if len(s) <= max_len else s[:max_len] + "..."


_TOKEN_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
SENSITIVE_TOKENS = {
    "id", "mrn", "eid", "uid", "guid", "uuid", "ssn", "key", "number", "num", "identifier", "passport", "emirates",
    "unified", "phone", "mobile", "tel", "telephone", "fax", "email", "mail", "address", "street", "zip", "postal",
    "postcode", "dob", "birth", "birthdate", "dateofbirth", "firstname", "lastname", "surname", "fullname",
    "middlename", "givenname", "familyname", "contact",
}
# "name" tek başına (ör. Patient.Name) ya da kişiye ait (FirstName, PatientName) → hassas; nesne adı değil
NON_PERSON_NAME = {
    "drug", "test", "item", "code", "product", "facility", "observation", "diagnosis", "procedure", "medication",
    "med", "lab", "display", "short", "long", "type", "category", "unit", "organization", "org", "department",
    "dept", "location", "ward", "service", "generic", "brand", "trade", "specimen", "order", "panel", "result",
    "component", "relation", "relationship", "condition", "problem", "allergy", "vaccine", "insurance", "payer",
    "plan", "file", "table", "column", "system", "coding", "value", "group", "class", "form", "route", "frequency",
    "status", "encounter", "visit", "clinic", "specialty", "nationality", "country", "ethnicity", "language",
    "religion", "source", "description", "desc",
}
_DATE_HINT = {"date", "dt", "time", "timestamp", "dob", "birth", "day", "on", "at"}
_DATE_SHAPE = re.compile(r"^(9{4}[-/.]99[-/.]99|99[-/.]99[-/.]9{4}|9{8}$|9[-/.]9{1,2}[-/.]9{4}|99[-/.]9[-/.]9{4})")


def name_tokens(name: str) -> list[str]:
    """'PatientID' → ['patient', 'id'] · 'date_of_birth' → ['date', 'of', 'birth'] · 'HSAA_PatientId' → [...]."""
    return [t.lower() for t in _TOKEN_RE.findall(str(name))]


def is_sensitive(name: str) -> bool:
    """Sütun adı kimlik / kişi adı / doğum tarihi / iletişim gibi mi → değeri hiç gösterilmez (yalnız şekli)."""
    toks = name_tokens(name)
    if any(t in SENSITIVE_TOKENS for t in toks) or "".join(toks) in SENSITIVE_TOKENS:
        return True
    return "name" in toks and not any(t in NON_PERSON_NAME for t in toks)


def patient_key(columns) -> str | None:
    """Hasta anahtarı sütunu (değer görünürlüğü 'en az 10 farklı hasta' kuralıyla): PatientID, patient_id, MRN …"""
    cols = [str(c) for c in columns]
    for c in cols:
        t = name_tokens(c)
        if any(x in t for x in ("patient", "person", "mpi", "member")) and \
                any(x in t for x in ("id", "key", "number", "num", "no", "mrn", "mpiid")):
            return c
    for c in cols:
        if "".join(name_tokens(c)) in ("mrn", "mpiid", "patient", "patientid"):
            return c
    return None


def looks_like_date(shape_text: str) -> bool:
    return bool(_DATE_SHAPE.match(shape_text or ""))


def _yyyymmdd_share(values: pd.Series) -> float:
    """8 haneli değerlerin kaçı 1900–2100 arası geçerli YYYYMMDD tarihi (SNOMED 73211009 değil)."""
    v = values[values.astype(str).str.fullmatch(r"\d{8}")]
    if not len(v):
        return 0.0
    d = pd.to_datetime(v, format="%Y%m%d", errors="coerce")
    return float(((d.dt.year >= 1900) & (d.dt.year <= 2100)).mean())


def profile_column(name: str, s: pd.Series) -> dict:
    """Örneklemdeki bir sütunun özeti: dolu %, farklı değer sayısı, en sık şekil, tür tahmini (değer yok)."""
    t = pd.Series([to_text(v) for v in s], dtype=object)
    nn = t.dropna()
    n, k = len(t), len(nn)
    shapes = nn.map(shape).value_counts()
    distinct = int(nn.nunique())
    numeric = float(pd.to_numeric(nn, errors="coerce").notna().mean()) if k else 0.0
    decimal = float(nn.astype(str).str.contains(r"\d[.,]\d", regex=True).mean()) if k else 0.0
    top = str(shapes.index[0]) if k else ""
    code_col = "code" in name_tokens(name)
    if not k:
        kind = "boş"
    elif looks_like_date(top) and not (top == "99999999" and (code_col or _yyyymmdd_share(nn) < 0.9)):
        kind = "tarih"
    elif code_col and decimal <= 0.5:
        kind = "kod"                               # sayısal da olsa kod (SNOMED, yerel numara): değer listesi
    elif re.fullmatch(r"9{5}(,9+)?", top) and any(x in _DATE_HINT for x in name_tokens(name)):
        kind = "tarih? (IRIS iç sayı: horolog)"
    elif numeric >= 0.95 and decimal > 0.5:
        kind = "sayı"                              # ondalıklı ölçüm (BMI, lab): her değer farklı olabilir
    elif distinct == k and k >= 20:
        kind = "benzersiz (kimlik?)"
    elif numeric >= 0.95:
        kind = "sayı" if distinct > 20 else "sayı / kategori"
    elif distinct <= 50:
        kind = "kategori"
    else:
        kind = "metin / kod"
    return {"column": name, "n": n, "filled": k, "filled_pct": round(100 * k / n, 1) if n else 0.0,
            "distinct": distinct, "shape": top, "shape_pct": int(round(100 * shapes.iloc[0] / k)) if k else 0,
            "kind": kind, "numeric_share": numeric, "decimal_share": decimal}


def hidden_reason(name: str, prof: dict) -> str | None:
    """Değerler neden gösterilmez (None = gösterilebilir; yine de ≥ 10 hasta kuralı uygulanır). Olay tarihi ve
    ondalıklı ölçüm çok çeşitli olsa da kimlik değildir: değer listesi yerine dağılımları basılır."""
    if is_sensitive(name):
        return "hassas sütun adı (kimlik / ad / doğum tarihi / iletişim)"
    if prof["kind"].startswith("tarih") or (prof["kind"] == "sayı" and prof.get("decimal_share", 0) > 0.5):
        return None
    if prof["kind"].startswith("benzersiz"):
        return "örneklemde her satır farklı (kimlik gibi)"
    if prof["filled"] and prof["distinct"] > 50 and prof["distinct"] / prof["filled"] > 0.5:
        return "çok çeşitli: örneklemde değerlerin yarıdan fazlası farklı (kimlik / serbest metin gibi)"
    return None


def table_profile(conn, schema: str, table: str, n_sample: int = SAMPLE_ROWS,
                  where: str | None = None) -> tuple[int, int, pd.DataFrame]:
    """→ (satır sayısı, örneklem satırı, sütun başına tip + profil + değer görünürlüğü)."""
    cols = list_columns(conn, schema, table)
    n_rows = count_rows(conn, schema, table, where)
    smp = sample(conn, schema, table, n_sample, where)
    by_upper = {str(c).upper(): c for c in smp.columns}
    rows = []
    for i, r in enumerate(cols.itertuples(index=False), start=1):
        src = by_upper.get(str(r.column).upper())
        s = smp[src] if src is not None else pd.Series([], dtype=object)
        p = profile_column(str(r.column), s)
        reason = hidden_reason(str(r.column), p)
        rows.append({"#": i, "column": r.column, "type": r.type, "filled_pct": p["filled_pct"],
                     "distinct": p["distinct"], "shape": f"{p['shape']} ({p['shape_pct']}%)" if p["filled"] else "",
                     "kind": p["kind"], "values": "gizli" if reason else "values ile"})
    return n_rows, len(smp), pd.DataFrame(rows)


def value_counts(conn, schema: str, table: str, column: str, where: str | None = None,
                 patient_col: str | None = "auto", top: int = 30, n_sample: int = SAMPLE_ROWS,
                 force_list: bool = False) -> dict:
    """Bir sütunun değer dağılımı, ifşa kurallarıyla:
    - hassas / kimlik gibi sütunda değer yok, yalnız şekiller (`hidden`)
    - değer, ≥ eşik farklı hastada (patient_col; 'auto' = `patient_key`) ya da anahtar yoksa ≥ eşik satırda
      geçiyorsa gösterilir; kalanlar `rest_small` (sayısı + toplam satır) olarak tek satırda.
    Tarih ve sürekli sayı sütunlarında değer listesi yerine örneklemden yüzdelikler (tarih: ay çözünürlüğünde);
    force_list ile liste de çıkar (aynı kurallarla)."""
    cols = list_columns(conn, schema, table)
    c = resolve_column(cols, column)
    col, typ = str(c["column"]), str(c["type"])
    if patient_col == "auto":
        pk = patient_key(cols["column"])
    elif patient_col and str(patient_col).lower() != "none":
        pk = str(resolve_column(cols, patient_col)["column"])
    else:
        pk = None
    if pk is not None and pk.upper() == col.upper():
        pk = None
    q, w, k = ident(schema, table), where_clause(where), threshold()
    tot = run_query(conn, f"SELECT COUNT(*) AS n, COUNT({iris.quote_ident(col)}) AS nn FROM {q}{w}")
    smp = sample(conn, schema, table, n_sample, where, columns=[col])
    s = smp.iloc[:, 0] if len(smp.columns) else pd.Series([], dtype=object)
    prof = profile_column(col, s)
    t = pd.Series([to_text(v) for v in s], dtype=object).dropna()
    shapes = t.map(shape).value_counts()
    out = {"schema": schema, "table": table, "column": col, "type": typ, "rows": int(tot.iloc[0, 0]),
           "filled": int(tot.iloc[0, 1]), "sample_rows": len(s), "profile": prof, "patient_col": pk,
           "hidden": hidden_reason(col, prof),
           "shapes": pd.DataFrame({"shape": shapes.index.astype(str),
                                   "pct": (100 * shapes.values / max(len(t), 1)).round(1)}).head(10),
           "values": None, "rest_small": None, "rest_top": None, "truncated": False, "quantiles": None,
           "distribution_only": False}
    if out["hidden"] or typ in STREAM_TYPES:
        if typ in STREAM_TYPES and not out["hidden"]:
            out["hidden"] = f"{typ} (stream) sütunu gruplanamaz"
        return out

    out["quantiles"] = _quantiles(t, prof["kind"], k)
    if not force_list and (prof["kind"].startswith("tarih") or prof["kind"] == "sayı"):
        out["distribution_only"] = True            # tarih / sürekli sayı: değer listesi yerine dağılım
        return out

    expr = iris.quote_ident(col)
    if dialect(conn) == "iris" and typ in CHAR_TYPES:
        expr = f"%EXACT({expr})"                  # IRIS varsayılan karşılaştırması büyük/küçük harf duyarsız
    np_sql = f", COUNT(DISTINCT {iris.quote_ident(pk)}) AS np" if pk else ""
    g = run_query(conn, limited(conn, f"{expr} AS v, COUNT(*) AS n{np_sql} FROM {q}{w} GROUP BY {expr} "
                                      "ORDER BY 2 DESC", GROUP_ROWS))
    g["v"] = [("<boş>" if to_text(v) is None else to_text(v)[:VALUE_MAX_LEN]) for v in g["v"]]
    g["n"] = pd.to_numeric(g["n"]).astype(int)
    if pk:
        g["np"] = pd.to_numeric(g["np"]).astype(int)
    measure = "np" if pk else "n"
    ok = g[g[measure] >= k]
    small = g[g[measure] < k]
    shown = ok.head(top)
    beyond = ok.iloc[len(shown):]
    out["values"] = shown.reset_index(drop=True)
    out["rest_small"] = {"values": int(len(small)), "rows": int(small["n"].sum())}
    out["rest_top"] = {"values": int(len(beyond)), "rows": int(beyond["n"].sum())}
    out["truncated"] = len(g) >= GROUP_ROWS
    return out


HOROLOG_EPOCH = pd.Timestamp("1840-12-31")      # IRIS $HOROLOG gün 0 (adapter'daki DATE_FORMAT="horolog")


def _quantiles(t: pd.Series, kind: str, k: int) -> dict | None:
    """Örneklemden yüzdelikler: sayı → p5…p95; tarih → ay çözünürlüğünde p5 / p50 / p95; horolog → tarihe çevrilmiş."""
    if len(t) < k:
        return None
    if kind == "tarih":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            d = pd.to_datetime(t, errors="coerce", format="mixed").dropna()
    elif kind.startswith("tarih?"):
        days = pd.to_numeric(t.str.split(",").str[0], errors="coerce").dropna()
        d = HOROLOG_EPOCH + pd.to_timedelta(days, unit="D")
    else:
        num = pd.to_numeric(t, errors="coerce").dropna()
        if len(num) < k or len(num) < 0.95 * len(t):
            return None
        return {f"p{p}": float(num.quantile(p / 100)) for p in (5, 25, 50, 75, 95)}
    if len(d) < k:
        return None
    return {f"p{p}": d.quantile(p / 100).strftime("%Y-%m") for p in (5, 50, 95)}
