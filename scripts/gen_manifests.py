#!/usr/bin/env python3
"""Generate client-specific manifests from the canonical ones.

Canonical, hand-edited:
  plugins/<name>/plugin.json     Agent Plugins 1.0.0 manifest (one per plugin)
  marketplace.source.json        marketplace name, owner, and which plugins it lists

Generated, never hand-edited:
  .claude-plugin/marketplace.json            read by Claude Code, Codex and Copilot CLI
  plugins/<name>/.claude-plugin/plugin.json  Claude Code's plugin manifest

Agent Plugins defines no marketplace format, so marketplace files are per client. To support
another client, add a function to GENERATORS; nothing else changes.

  python scripts/gen_manifests.py           # write
  python scripts/gen_manifests.py --check   # exit 1 if any generated file is stale
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Fields Claude Code's plugin manifest shares with Agent Plugins.
CLAUDE_PLUGIN_FIELDS = ("name", "version", "description", "author", "homepage", "repository",
                        "license", "keywords")


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def claude(source: dict, plugins: dict[str, dict]) -> dict[str, dict]:
    files = {
        ".claude-plugin/marketplace.json": {
            "name": source["name"],
            "owner": source["owner"],
            "metadata": {"description": source["description"]},
            # Version lives only in each plugin manifest; setting it in both places lets
            # them drift.
            "plugins": [{"name": e["name"], "source": f"./plugins/{e['name']}",
                         "description": plugins[e["name"]]["description"],
                         **({"category": e["category"]} if e.get("category") else {})}
                        for e in source["plugins"]],
        }
    }
    for name, manifest in plugins.items():
        files[f"plugins/{name}/.claude-plugin/plugin.json"] = {
            k: manifest[k] for k in CLAUDE_PLUGIN_FIELDS if k in manifest}
    return files


GENERATORS = (claude,)


def build() -> dict[str, str]:
    source = load(ROOT / "marketplace.source.json")
    plugins = {p.parent.name: load(p) for p in sorted(ROOT.glob("plugins/*/plugin.json"))}
    listed = [e["name"] for e in source["plugins"]]
    if sorted(listed) != sorted(plugins):
        raise SystemExit(f"marketplace.source.json lists {sorted(listed)} but plugins/ has "
                         f"{sorted(plugins)}")
    out: dict[str, str] = {}
    for generate in GENERATORS:
        for rel, data in generate(source, plugins).items():
            out[rel] = json.dumps(data, indent=2) + "\n"
    return out


def main(argv: list[str]) -> int:
    check = "--check" in argv
    stale = []
    for rel, text in build().items():
        path = ROOT / rel
        if path.exists() and path.read_text() == text:
            continue
        stale.append(rel)
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    if check and stale:
        print("stale generated manifests (run scripts/gen_manifests.py):", *stale, sep="\n  ")
        return 1
    print(("up to date" if not stale else "wrote " + ", ".join(stale)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
