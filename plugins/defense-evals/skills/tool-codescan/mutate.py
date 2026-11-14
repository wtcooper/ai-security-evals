#!/usr/bin/env python3
"""Anti-memorization mutation of a benchmark snapshot (design doc §2.1.3): rename identifiers,
routes, module/package names and branding consistently across the tree, and emit a rename map so
ground-truth labels (file paths, function names) can be translated to the mutant.

  python3 mutate.py <src-dir> <dst-dir> --map rename_map.json [--seed 0] [--rename-files]
      [--extra "OldName=NewName" ...] [--exts .py,.js,.ts,.go,.java,.rb,.php,.md,.yml,.yaml,.json,.toml]

Renames: user-defined names (functions/classes/routes) discovered by simple regexes per language,
plus --extra pairs. Keeps semantics: only identifiers with >= 6 chars not in a stoplist of
language/framework keywords are renamed, using a deterministic seed. Review the map before use.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import sys
from pathlib import Path

STOP = set("""self cls None True False import from return async await class def lambda yield with while
for else elif except finally raise assert global nonlocal print object super property staticmethod
classmethod request response session require module exports export default function const let var
this new typeof instanceof switch case break continue throw catch delete void package func struct
interface type range select defer chan public private protected static final abstract extends
implements throws string number boolean length append push pop items keys values update format
strip split join replace encode decode read write open close send recv route router app main
config settings models views utils tests test setup teardown handler handlers middleware
""".split())
DEF_RE = {
    ".py": re.compile(r"^\s*(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]{5,})", re.M),
    ".js": re.compile(r"(?:function\s+|class\s+|const\s+|let\s+)([A-Za-z_$][A-Za-z0-9_$]{5,})\s*[(=:]", re.M),
    ".ts": re.compile(r"(?:function\s+|class\s+|const\s+|let\s+|interface\s+)([A-Za-z_$][A-Za-z0-9_$]{5,})\s*[(=:<{]", re.M),
    ".go": re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]{5,})|^\s*type\s+([A-Za-z_][A-Za-z0-9_]{5,})", re.M),
    ".java": re.compile(r"(?:class|interface|enum)\s+([A-Za-z_][A-Za-z0-9_]{5,})|\b(?:public|private|protected|static)\s+[\w<>\[\]]+\s+([A-Za-z_][A-Za-z0-9_]{5,})\s*\(", re.M),
    ".rb": re.compile(r"^\s*(?:def|class|module)\s+(?:self\.)?([A-Za-z_][A-Za-z0-9_]{5,})", re.M),
    ".php": re.compile(r"(?:function|class)\s+([A-Za-z_][A-Za-z0-9_]{5,})", re.M),
}
ROUTE_RE = re.compile(r"""(["'`])/([a-z][a-z0-9_-]{3,})(?=[/"'`?{])""")
SYL = ["ka", "to", "ri", "ne", "mo", "su", "va", "li", "do", "pe", "zu", "ra", "mi", "ko", "ta", "be"]


def synth(rng: random.Random, style: str) -> str:
    w = "".join(rng.choice(SYL) for _ in range(rng.randint(2, 3)))
    if style == "Camel":
        return w.capitalize() + rng.choice(SYL).capitalize()
    if style == "camel":
        return w + rng.choice(SYL).capitalize()
    return w + "_" + rng.choice(SYL)


def style_of(name: str) -> str:
    if name[0].isupper():
        return "Camel"
    if "_" in name:
        return "snake"
    return "camel"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path); ap.add_argument("dst", type=Path)
    ap.add_argument("--map", type=Path, required=True); ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rename-files", action="store_true"); ap.add_argument("--extra", action="append", default=[])
    ap.add_argument("--exts", default=".py,.js,.ts,.go,.java,.rb,.php,.md,.yml,.yaml,.json,.toml,.html,.txt")
    ap.add_argument("--max", type=int, default=400, help="max identifiers to rename")
    a = ap.parse_args()
    exts = set(a.exts.split(","))
    rng = random.Random(a.seed)
    files = [p for p in a.src.rglob("*") if p.is_file() and p.suffix in exts and ".git" not in p.parts and "node_modules" not in p.parts]
    names, routes = set(), set()
    for p in files:
        try:
            txt = p.read_text(errors="ignore")
        except Exception:
            continue
        rx = DEF_RE.get(p.suffix)
        if rx:
            for m in rx.finditer(txt):
                for g in m.groups():
                    if g and g.lower() not in STOP and not g.startswith("__"):
                        names.add(g)
        for m in ROUTE_RE.finditer(txt):
            if m.group(2) not in STOP:
                routes.add(m.group(2))
    rename = {}
    for k in a.extra:
        o, n = k.split("=", 1); rename[o] = n
    pool = sorted(names)[: a.max]
    used = set(rename.values())
    for n in pool:
        while True:
            cand = synth(rng, style_of(n))
            if cand not in used and cand not in names:
                used.add(cand); break
        rename.setdefault(n, cand)
    for r in sorted(routes):
        while True:
            cand = synth(rng, "snake").replace("_", "-")
            if cand not in used:
                used.add(cand); break
        rename.setdefault("/" + r, "/" + cand)
    ident_pat = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted((k for k in rename if not k.startswith("/")), key=len, reverse=True)) + r")\b") if any(not k.startswith("/") for k in rename) else None
    route_pat = re.compile(r"(?<=[\"'`])(" + "|".join(re.escape(k) for k in sorted((k for k in rename if k.startswith("/")), key=len, reverse=True)) + r")(?=[/\"'`?{])") if any(k.startswith("/") for k in rename) else None
    if a.dst.exists():
        shutil.rmtree(a.dst)
    shutil.copytree(a.src, a.dst, ignore=shutil.ignore_patterns(".git", "node_modules"))
    file_map = {}
    for p in [q for q in a.dst.rglob("*") if q.is_file() and q.suffix in exts]:
        try:
            txt = p.read_text(errors="ignore")
        except Exception:
            continue
        new = txt
        if ident_pat:
            new = ident_pat.sub(lambda m: rename[m.group(1)], new)
        if route_pat:
            new = route_pat.sub(lambda m: rename[m.group(1)], new)
        if new != txt:
            p.write_text(new)
        if a.rename_files and ident_pat and ident_pat.search(p.stem):
            newp = p.with_name(ident_pat.sub(lambda m: rename[m.group(1)], p.stem) + p.suffix)
            p.rename(newp); file_map[str(p.relative_to(a.dst))] = str(newp.relative_to(a.dst))
    a.map.write_text(json.dumps({"seed": a.seed, "identifiers": rename, "files": file_map}, indent=1) + "\n")
    print(f"renamed {len(rename)} identifiers/routes, {len(file_map)} files -> {a.dst}; map: {a.map}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
