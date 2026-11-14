"""Load the feature templates and render them as the reference documents.

  python scripts/templates.py --list
  python scripts/templates.py --render          # rewrite references/<feature>.md and benchmarks.md
  python scripts/templates.py --check           # exit 1 if a reference file is out of date

`templates/<feature>.json` is the source of truth: the review script reads it, and the
reference documents people read are generated from it, so the two cannot drift.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
TEMPLATES = SKILL / "templates"
REFERENCES = SKILL / "references"
GENERATED = ("Generated from `templates/{name}` by `scripts/templates.py --render`. Edit the "
             "JSON and render again; a unit test fails if this file is out of date.")


def features() -> list[str]:
    return sorted(p.stem for p in TEMPLATES.glob("*.json") if not p.name.startswith("_"))


def load(feature: str) -> dict:
    path = TEMPLATES / f"{feature}.json"
    if not path.is_file():
        raise ValueError(f"unknown feature {feature!r}; choose from {features()}")
    return json.loads(path.read_text())


def frameworks() -> dict:
    return json.loads((TEMPLATES / "_frameworks.json").read_text())


def benchmarks() -> dict:
    return json.loads((TEMPLATES / "_benchmarks.json").read_text())["benchmarks"]


def framework_line(threat: dict, fw: dict) -> str:
    parts = []
    for key, label in (("owasp_llm", "OWASP LLM"), ("owasp_agentic", "OWASP Agentic"),
                       ("atlas", "MITRE ATLAS")):
        if threat[key]:
            parts.append(f"{label}: " + ", ".join(f"{i} {fw[key][i]}" for i in threat[key]))
    return " · ".join(parts) if parts else \
        "Framework ids: none. No entry was verified to fit, so none is given."


def render_feature(feature: str) -> str:
    t, fw, bm = load(feature), frameworks(), benchmarks()
    out = [f"# {t['title']} — threat and test template", "",
           GENERATED.format(name=f"{feature}.json"), "",
           "## What the feature changes about the trust boundary", ""]
    out += [f"- {line}" for line in t["trust_boundary"]]
    out += ["", "## Deployment context to capture", "",
            "Besides the scope and the six dimensions in `deployment-context.md`, ask:", ""]
    out += [f"- {q}" for q in t["context_questions"]]
    out += ["", "## Threats", ""]
    for th in t["threats"]:
        out += [f"### {th['id']} {th['title']}", "", th["description"], "",
                framework_line(th, fw), "", "Review questions", ""]
        out += [f"{n}. {q}" for n, q in enumerate(th["questions"], 1)]
        out += ["", "Vendor evidence to look for", ""] + [f"- {v}" for v in th["vendor_evidence"]]
        out += ["", "Existing benchmarks", ""]
        if th["benchmarks"]:
            for key in th["benchmarks"]:
                b = bm[key]
                out.append(f"- **{b['name']}** ({b['ref']}). {b['measures']} {b['route']} "
                           f"Limits: {b['limits']}")
        else:
            out.append("- None found (survey of 2026-11-14).")
        if th["own_tests"]:
            out += ["", "Your own tests through this repo's skills", ""]
            out += [f"- `{o['skill']}`: {o['how']}" for o in th["own_tests"]]
        out += ["", "No standardized test for", ""] + [f"- {g}" for g in th["no_standard_test"]]
        out.append("")
    out += ["## Sources", "",
            "Framework ids: " + "; ".join(fw["sources"].values()) + ".",
            "Benchmarks: see `benchmarks.md` for what was and was not verified about each.", ""]
    return "\n".join(out)


def render_benchmarks() -> str:
    data = json.loads((TEMPLATES / "_benchmarks.json").read_text())
    used: dict[str, list[str]] = {}
    for feature in features():
        for th in load(feature)["threats"]:
            for key in th["benchmarks"]:
                used.setdefault(key, []).append(th["id"])
    out = ["# Benchmarks named in the templates", "",
           GENERATED.format(name="_benchmarks.json"), "",
           f"Surveyed {data['surveyed']}. Each entry says what the benchmark measures, how it "
           "can be run from this repo if at all, what it leaves out, and how the description "
           "was verified. \"Paper abstract only\" means exactly that: the code was not "
           "fetched or run, and licence and dataset details were not checked.", "",
           "A benchmark result is evidence about a model or an agent in the benchmark's own "
           "environment. It is not evidence about a vendor's product unless the vendor ran it "
           "on that product and says so.", ""]
    for key, b in data["benchmarks"].items():
        out += [f"## {b['name']}", "", f"- Reference: {b['ref']}", f"- Measures: {b['measures']}",
                f"- Route: {b['route']}", f"- Limits: {b['limits']}",
                f"- Verified: {b['verified']}",
                f"- Named under: {', '.join(used.get(key, [])) or 'no threat'}", ""]
    return "\n".join(out)


def rendered() -> dict[Path, str]:
    files = {REFERENCES / f"{f}.md": render_feature(f) for f in features()}
    files[REFERENCES / "benchmarks.md"] = render_benchmarks()
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if args.list:
        for f in features():
            t = load(f)
            print(f"{f:<20} {len(t['threats'])} threats  {t['title']}")
        return 0
    stale = [p for p, text in rendered().items() if not p.is_file() or p.read_text() != text]
    if args.render:
        for p, text in rendered().items():
            p.write_text(text)
        print(f"rendered {len(rendered())} reference file(s), {len(stale)} changed")
        return 0
    if args.check:
        for p in stale:
            print(f"out of date: {p.relative_to(SKILL)}")
        return 1 if stale else 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
