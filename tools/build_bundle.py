"""One-file bundle for a VM that cannot `git pull`: the code of the `bash tools/enclave.sh run` steps in one .py file.

The bundle carries tools/enclave.py, the step scripts (default: the Phase 1 steps ingest, nb0, nb1, kpi) and every
src/sandbox module they import, unchanged, compressed and base64-encoded (ASCII only: a clipboard copy cannot
mangle →, ≥ …). Copy the file by hand into the repo on the VM and run it there:

  python tools/build_bundle.py                       # → dist/sandbox_bundle.py (ingest, nb0, nb1, kpi)
  python tools/build_bundle.py --steps ingest        # only the ingest
  # on the VM, inside the repo:
  python3 sandbox_bundle.py bundle-info              # file check, what it carries, which repo files are older
  python3 sandbox_bundle.py run ingest --cohorts c1 c2   # = bash tools/enclave.sh run ingest --cohorts c1 c2
  python3 sandbox_bundle.py run nb0                  # = bash tools/enclave.sh run nb0 (same for nb1, kpi)

At run time the bundle's modules are imported instead of the repo's src/ and tools/ files (the repo is only read
for data/, outputs/, .env and src/sandbox/reference/ddc.csv.gz, whose SHA-256 is checked). The last line holds a
hash of every line above it: a copy that lost or changed a line is refused. The audit records the bundled files'
SHA-256, the commit the bundle was built from and the bundle id (audit.code_fingerprint is replaced); the COPY
block header shows `commit <sha> bundle <id>`. The build is deterministic: the same commit gives the same file.
"""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import re
import subprocess
import sys
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import enclave  # noqa: E402  (standard library only at import)

ENTRY = "tools/enclave.py"
DEFAULT_STEPS = ["ingest", "nb0", "nb1", "kpi"]          # Phase 1 (C1 / C2): docs/faz1_c1_c2.md
BUNDLE_NAME = "sandbox_bundle.py"
# Files the bundled code reads from the repo on the VM (not embedded): path → SHA-256 checked before a run
RESOURCES = ["src/sandbox/reference/ddc.csv.gz"]
CHECK_PREFIX = "# file-check: "
PAYLOAD_MARK = "# ---- PAYLOAD (zlib + base64; read by the code above) ----"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def module_file(name: str) -> str | None:
    """Module name → repo file (src/sandbox/… or tools/<name>.py), None for anything else (stdlib, pandas, iris …)."""
    parts = name.split(".")
    if parts[0] == "sandbox":
        p = REPO_ROOT / "src" / Path(*parts)
        for f in (p / "__init__.py", p.with_suffix(".py")):
            if f.is_file():
                return f.relative_to(REPO_ROOT).as_posix()
        return None
    f = REPO_ROOT / "tools" / f"{name}.py"
    return f.relative_to(REPO_ROOT).as_posix() if len(parts) == 1 and f.is_file() else None


def module_of(rel: str) -> tuple[str, bool]:
    """Repo file → (module name, is package). tools/x.py → x (the tools put tools/ on sys.path)."""
    parts = rel.removesuffix(".py").split("/")[1:]
    if parts[-1] == "__init__":
        return ".".join(parts[:-1]), True
    return ".".join(parts), False


def imported_names(rel: str) -> set[str]:
    """Every module name an import statement in the file may refer to (also imports inside functions)."""
    tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"), rel)
    mod, is_pkg = module_of(rel) if rel.startswith(("src/", "tools/")) else ("__main__", False)
    pkg = mod.split(".") if is_pkg else mod.split(".")[:-1]
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                parts = a.name.split(".")
                names.update(".".join(parts[:i]) for i in range(1, len(parts) + 1))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg[:len(pkg) - (node.level - 1)] + (node.module.split(".") if node.module else [])
            else:
                base = node.module.split(".")
            names.update(".".join(base[:i]) for i in range(1, len(base) + 1))
            names.update(".".join(base + [a.name]) for a in node.names)     # `from pkg import submodule`
    return names


def closure(entries: list[str]) -> list[str]:
    todo, seen = list(entries), set()
    while todo:
        rel = todo.pop()
        if rel in seen:
            continue
        seen.add(rel)
        todo += [f for n in imported_names(rel) if (f := module_file(n)) and f not in seen]
    return sorted(seen)


def _git(*args: str) -> str:
    p = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else ""


def normalized_lines(text: str) -> list[str]:
    """What the file check hashes: line endings and trailing spaces ignored (an editor may change them)."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def file_check(lines: list[str]) -> str:
    return sha256_bytes("\n".join(lines).encode("utf-8"))[:16]


def build(steps: list[str], allow_dirty: bool = False, name: str = BUNDLE_NAME) -> tuple[str, dict]:
    """→ (bundle text, meta)."""
    unknown = [s for s in steps if s not in enclave.STEPS]
    if unknown:
        raise SystemExit(f"unknown step: {', '.join(unknown)} (steps: {', '.join(enclave.STEPS)})")
    scripts = [enclave.STEPS[s][0] for s in steps]
    files = closure([ENTRY, *scripts])
    dirty = _git("status", "--porcelain", "--", *files, *RESOURCES)
    if dirty and not allow_dirty:
        raise SystemExit("uncommitted changes in bundled files — commit first (the audit names the commit) "
                         f"or pass --allow-dirty:\n{dirty}")
    sources = {rel: (REPO_ROOT / rel).read_text(encoding="utf-8") for rel in files}
    nabidh = sources.get("src/sandbox/io/adapters/nabidh.py", "")
    m = re.search(r'^INGEST_VERSION = "([^"]+)"', nabidh, re.MULTILINE)
    per_file = {rel: sha256_bytes((REPO_ROOT / rel).read_bytes()) for rel in files}
    meta = {
        "steps": steps,
        "ingest_version": m.group(1) if m else "?",
        "git": {"commit": _git("rev-parse", "HEAD") or None, "dirty": bool(dirty)},
        "files": per_file,
        # same formula as audit.code_fingerprint, over the bundled files
        "combined_sha256": sha256_bytes("".join(per_file[k] for k in sorted(per_file)).encode()),
        "resources": {rel: sha256_bytes((REPO_ROOT / rel).read_bytes()) for rel in RESOURCES},
    }
    raw = json.dumps({"meta": meta, "files": sources}, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":")).encode("utf-8")
    payload_sha = sha256_bytes(raw)
    meta["payload_sha256"] = payload_sha
    blob = "\n".join("# " + ln for ln in base64.encodebytes(zlib.compress(raw, 9)).decode("ascii").split())

    commit = (meta["git"]["commit"] or "?")[:7] + ("+changes" if dirty else "")
    doc = "\n".join([
        f'"""Albert Health x DHA sandbox - one-file bundle {payload_sha[:12]}: run {", ".join(steps)}',
        "",
        f"Built by tools/build_bundle.py from commit {commit} (ingest v{meta['ingest_version']}). It carries these",
        "repo files unchanged (compressed in PAYLOAD below) and runs them instead of the repo's copies:",
        *[f"  {rel}" for rel in files],
        "Put this file in the repo root on the VM and run it there (the repo supplies data/, outputs/, .env and",
        f"{', '.join(RESOURCES)}):",
        f"  python3 {name} bundle-info                  # file check, contents, which repo files differ",
        *[f"  python3 {name} run ingest --cohorts c1 c2   # = bash tools/enclave.sh run ingest --cohorts c1 c2"
          for s in steps if s == "ingest"],
        *[f"  python3 {name} run {s:<24s}# = bash tools/enclave.sh run {s}" for s in steps if s != "ingest"],
        f"  python3 {name} help                         # every enclave.sh command",
        "The last line is a hash of all lines above it: a file changed while copying is refused. The",
        "embedded code is the comment block at the end (bundle-extract DIR writes it out as files).",
        '"""',
    ])
    text = (BOOTSTRAP.replace("@@DOC@@", doc).replace("@@PAYLOAD_SHA256@@", payload_sha)
            .replace("@@PAYLOAD_MARK@@", PAYLOAD_MARK) + f"\n{PAYLOAD_MARK}\n{blob}\n")
    lines = normalized_lines(text)
    text = "\n".join(lines) + f"\n{CHECK_PREFIX}{file_check(lines)}\n"
    if not text.isascii():
        raise AssertionError("bundle text must be ASCII (clipboard safety)")
    return text, meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="One-file bundle of the enclave steps (for a VM without git pull)")
    ap.add_argument("--steps", nargs="+", default=DEFAULT_STEPS,
                    help=f"run steps to carry ({', '.join(enclave.STEPS)}); default {' '.join(DEFAULT_STEPS)}")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "dist" / BUNDLE_NAME, help=f"default dist/{BUNDLE_NAME}")
    ap.add_argument("--allow-dirty", action="store_true", help="build from uncommitted files (audit shows +changes)")
    a = ap.parse_args(argv)
    text, meta = build(a.steps, a.allow_dirty, a.out.name)
    out = a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    commit = (meta["git"]["commit"] or "?")[:7] + ("+changes" if meta["git"]["dirty"] else "")
    print(f"{out}  ({len(text.encode()) / 1024:.0f} KB, {text.count(chr(10))} lines)")
    print(f"bundle {meta['payload_sha256'][:12]} · commit {commit} · ingest v{meta['ingest_version']} · "
          f"steps: {', '.join(a.steps)} · {len(meta['files'])} files")
    print(f"file check: {text.rstrip().rsplit(CHECK_PREFIX, 1)[1]}  (the VM's `bundle-info` must show the same)")
    print(f"VM: save it inside the repo as {out.name}, then: python3 {out.name} bundle-info")
    return 0


# ---------------------------------------------------------------------------------------------------------------
# The bundle's own code (standard library only, ASCII). @@…@@ are filled in by build().
# ---------------------------------------------------------------------------------------------------------------
BOOTSTRAP = r'''#!/usr/bin/env python3
@@DOC@@
import base64
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
import linecache
import os
import sys
import types
import zlib
from pathlib import Path

PAYLOAD_SHA256 = "@@PAYLOAD_SHA256@@"
CHECK_PREFIX = "# file-check: "
PAYLOAD_MARK = "@@PAYLOAD_MARK@@"
BUNDLE = Path(os.path.abspath(__file__))
NAME = BUNDLE.name
ID = PAYLOAD_SHA256[:12]


def stop(msg):
    print(f"[{NAME}] {msg}", file=sys.stderr, flush=True)
    sys.exit(2)


def normalized_lines(text):
    lines = [ln.rstrip() for ln in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def self_check():
    """The last line is a hash of every line above it (line endings / trailing spaces ignored).
    Returns (check, payload lines)."""
    lines = normalized_lines(BUNDLE.read_text(encoding="utf-8", errors="replace"))
    if not lines or not lines[-1].startswith(CHECK_PREFIX):
        stop(f"the last line ({CHECK_PREFIX}...) is missing: the copy is incomplete. Copy the whole file again.")
    want = lines[-1][len(CHECK_PREFIX):].strip()
    got = hashlib.sha256("\n".join(lines[:-1]).encode("utf-8")).hexdigest()[:16]
    if got != want:
        stop(f"file check {got}, expected {want}: the file changed while copying (a line lost or edited). "
             "Copy the whole file again.")
    if PAYLOAD_MARK not in lines:
        stop(f"the line '{PAYLOAD_MARK}' is missing. Copy the whole file again.")
    return got, [ln.lstrip("# ") for ln in lines[lines.index(PAYLOAD_MARK) + 1:-1]]


def load_payload(blob):
    try:
        raw = zlib.decompress(base64.b64decode("".join(blob)))
    except Exception as e:
        stop(f"the embedded code cannot be read ({type(e).__name__}). Copy the whole file again.")
    if hashlib.sha256(raw).hexdigest() != PAYLOAD_SHA256:
        stop("the embedded code does not match its checksum. Copy the whole file again.")
    return json.loads(raw.decode("utf-8"))


def repo_root():
    if os.environ.get("SANDBOX_BUNDLE_ROOT"):
        return Path(os.environ["SANDBOX_BUNDLE_ROOT"]).resolve()
    for start in (Path.cwd().resolve(), BUNDLE.parent):
        for d in (start, *start.parents):
            if (d / "src" / "sandbox").is_dir():
                return d
    stop("repo folder not found (a folder with src/sandbox). Run this from the repo root "
         "(~/Desktop/albert-dha/albert-dha-sandbox) or set SANDBOX_BUNDLE_ROOT=<repo folder>.")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def module_of(rel):
    """src/sandbox/io/iris.py -> sandbox.io.iris; tools/enclave.py -> enclave; notebooks are scripts only."""
    parts = rel[:-3].split("/")
    if parts[0] not in ("src", "tools"):
        return None
    parts = parts[1:]
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


class Importer(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Serves the embedded modules ahead of the repo's files. __file__ is the repo path, so config.REPO_ROOT,
    .env and the DDC reference resolve in the repo; tracebacks show the embedded lines. A package's __path__ is
    empty: a module that is not embedded is not picked up from the repo's (older) src/."""

    def __init__(self, root, files):
        self.root, self.files = root, files
        self.modules = {m: rel for rel in files if (m := module_of(rel))}

    def find_spec(self, fullname, path=None, target=None):
        rel = self.modules.get(fullname)
        if rel is None:
            return None
        return importlib.util.spec_from_loader(fullname, self, origin=str(self.root / rel),
                                               is_package=rel.endswith("/__init__.py"))

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        rel = self.modules[module.__name__]
        module.__file__ = str(self.root / rel)
        exec(self.compile(rel), module.__dict__)

    def get_source(self, fullname):
        return self.files[self.modules[fullname]]

    def compile(self, rel):
        path, src = str(self.root / rel), self.files[rel]
        linecache.cache[path] = (len(src), None, src.splitlines(True), path)
        return compile(src, path, "exec", dont_inherit=True)

    def run_script(self, rel, args):
        """Run an embedded script as __main__ (what `python <script> args` does)."""
        path = str(self.root / rel)
        main = types.ModuleType("__main__")
        main.__file__ = path
        sys.modules["__main__"] = main
        sys.argv = [path, *args]
        exec(self.compile(rel), main.__dict__)


def resource_problems(root, meta):
    commit = (meta["git"]["commit"] or "?")[:7]
    out = []
    for rel, want in meta["resources"].items():
        p = root / rel
        if not p.is_file():
            out.append(f"{rel} is missing in the repo ({root})")
        elif sha256_file(p) != want:
            out.append(f"{rel} differs from the one at commit {commit}")
    return out


def label(meta):
    git = meta["git"]
    return f"{(git['commit'] or '?')[:7]}{'+changes' if git['dirty'] else ''} bundle {ID}"


def info(root, meta, files, check):
    print(f"Bundle {ID} - commit {label(meta).split(' ')[0]} - ingest v{meta['ingest_version']} - "
          f"steps: run {', '.join(meta['steps'])}")
    print(f"File check: OK ({check})")
    print(f"Repo root: {root}")
    print(f"Embedded files ({len(files)}), against the repo's copy on this machine (the bundle runs its own):")
    for rel in sorted(files):
        p = root / rel
        state = ("not in the repo" if not p.is_file() else
                 "same" if sha256_file(p) == meta["files"][rel] else "differs (the repo has another version)")
        print(f"  {rel:42s} {state}")
    bad = resource_problems(root, meta)
    for rel in meta["resources"]:
        print(f"Read from the repo: {rel} - {'PROBLEM' if any(rel in b for b in bad) else 'OK'}")
    for b in bad:
        print(f"  PROBLEM: {b}")
    print(f"Next: python3 {NAME} run ingest --cohorts c1 c2")
    return 1 if bad else 0


def extract(files, target):
    target = Path(target)
    if target.exists() and any(target.iterdir()):
        stop(f"{target} is not empty")
    for rel, src in files.items():
        p = target / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding="utf-8")
    print(f"{len(files)} files written under {target} (for reading; the bundle does not use them)")
    return 0


USAGE = f"""python3 {NAME} COMMAND ...   (from the repo root; same commands as bash tools/enclave.sh)
  bundle-info                     file check, what the bundle carries, DDC reference check
  run ingest --cohorts c1 c2      IRIS -> canonical (data/canonical/nabidh/...) + COPY block
  run nb0 | run nb1 | run kpi     the other steps it carries (bundle-info lists them)
  run all                         ingest c1 c2 -> nb0 -> nb1 -> kpi in one COPY block
  checks [1a 1c 1d]               Phase 1 step 1 value checks (c1 c2) in one block
  mapping c1 c2 | schemas | ...   the other enclave.sh commands, with the bundle's adapter
  audit-close [RUN_ID --reason ..] list runs left open in the audit log / close one as abandoned
  bundle-extract DIR              write the embedded source files to DIR (to read them)
Every COPY block is also appended to logs/enclave/<UTC date>.log in the repo root (the block only).
"""


def main():
    check, blob = self_check()
    payload = load_payload(blob)
    meta, files = payload["meta"], payload["files"]
    args = sys.argv[1:]
    if args[:1] == ["bundle-extract"]:
        if len(args) != 2:
            stop(f"usage: python3 {NAME} bundle-extract DIR")
        return extract(files, args[1])
    root = repo_root()
    if args[:1] == ["bundle-info"]:
        return info(root, meta, files, check)
    os.environ["SANDBOX_BUNDLE_ROOT"] = str(root)      # the step subprocess (this file again) uses the same repo
    imp = Importer(root, files)
    sys.meta_path.insert(0, imp)

    from sandbox import audit

    fingerprint = {"combined_sha256": meta["combined_sha256"], "files": meta["files"], "git": meta["git"],
                   "bundle": {"id": ID, "payload_sha256": PAYLOAD_SHA256, "file": NAME, "file_check": check}}
    audit.code_fingerprint = lambda: json.loads(json.dumps(fingerprint))

    if args[:1] == ["--bundle-exec"]:                   # internal: a step script, started by `run`
        if len(args) < 2 or args[1] not in files:
            stop(f"--bundle-exec: not an embedded script: {args[1:2]}")
        bad = resource_problems(root, meta)
        if bad:
            stop("; ".join(bad))
        imp.run_script(args[1], args[2:])
        return 0

    import enclave

    def step_command(step):
        script = enclave.STEPS[step][0]
        if script not in files:
            raise RuntimeError(f"run {step}: {script} is not in this bundle (it carries: run "
                               f"{', '.join(meta['steps'])}); for the repo's copy: bash tools/enclave.sh run {step}")
        bad = resource_problems(root, meta)
        if bad:
            raise RuntimeError("; ".join(bad))
        return [sys.executable, str(BUNDLE), "--bundle-exec", script]

    enclave.CMD = f"python3 {NAME}"
    enclave.commit_label = lambda: label(meta)
    enclave.step_command = step_command
    if not args or args[0] in ("help", "-h", "--help"):
        print(USAGE)
    return enclave.main(args)


if __name__ == "__main__":
    sys.exit(main())
'''


if __name__ == "__main__":
    sys.exit(main())
