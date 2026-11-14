#!/usr/bin/env python3
"""Check every plugin against Agent Plugins 1.0.0 and every skill against the Agent Skills
standard frontmatter. Stdlib only, so it runs in CI without any agent CLI installed.

  python scripts/check_plugins.py            # exit 1 on any violation

What it enforces:
  * plugins/<name>/plugin.json: required `$schema` and `name`, the closed field set and the
    name rules of the 1.0.0 schema; `name` equals the directory name.
  * Skills are immediate children of `skills/`, each with a SKILL.md.
  * SKILL.md frontmatter uses standard fields only (client-specific fields make a skill
    fail to load in other clients), `name` equals the directory, length limits hold.
  * Skill names are unique across plugins.
  * No path inside a plugin resolves outside it (symlinks included).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
PLUGIN_FIELDS = {"$schema": str, "name": str, "version": str, "description": str, "author": dict,
                 "homepage": str, "repository": str, "license": str, "keywords": list,
                 "extensions": dict}
PLUGIN_NAME = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
SKILL_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LIMITS = {"name": 64, "description": 1024, "compatibility": 500}


def check_manifest(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return [f"{path}: not readable JSON ({exc})"]
    if not isinstance(data, dict):
        return [f"{path}: top level must be an object"]
    errs = []
    if data.get("$schema") != PLUGIN_SCHEMA:
        errs.append(f"{path}: $schema must be {PLUGIN_SCHEMA}")
    name = data.get("name")
    if not isinstance(name, str) or not 1 <= len(name) <= 64 or not PLUGIN_NAME.match(name):
        errs.append(f"{path}: invalid name {name!r}")
    elif name != path.parent.name:
        errs.append(f"{path}: name {name!r} does not match directory {path.parent.name!r}")
    for key, value in data.items():
        if key not in PLUGIN_FIELDS:
            errs.append(f"{path}: unknown field {key!r} (the 1.0.0 schema is closed)")
        elif not isinstance(value, PLUGIN_FIELDS[key]):
            errs.append(f"{path}: {key} must be {PLUGIN_FIELDS[key].__name__}")
    author = data.get("author")
    if isinstance(author, dict) and (set(author) - {"name", "email", "url"}
                                     or not all(isinstance(v, str) for v in author.values())):
        errs.append(f"{path}: author allows only string fields name, email, url")
    if isinstance(data.get("keywords"), list) and not all(
            isinstance(k, str) for k in data["keywords"]):
        errs.append(f"{path}: keywords must be strings")
    return errs


def parse_frontmatter(text: str) -> dict[str, str] | None:
    """Top-level keys of a YAML frontmatter block, with scalar and folded/literal values.
    Enough for validation; nested values are returned as their raw text."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    out: dict[str, str] = {}
    key = None
    for line in text[4:end].split("\n"):
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m and not line.startswith((" ", "\t")):
            key, value = m.group(1), m.group(2).strip()
            out[key] = "" if value in (">", ">-", ">+", "|", "|-", "|+") else value.strip("\"'")
        elif key is not None and line.strip():
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


def check_skill(skill_dir: Path) -> list[str]:
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        return [f"{skill_dir}: no SKILL.md"]
    fm = parse_frontmatter(md.read_text())
    if fm is None:
        return [f"{md}: missing YAML frontmatter"]
    errs = [f"{md}: non-standard frontmatter field {k!r}" for k in fm if k not in SKILL_FIELDS]
    for required in ("name", "description"):
        if not fm.get(required):
            errs.append(f"{md}: {required} is required")
    for key, limit in LIMITS.items():
        if len(fm.get(key, "")) > limit:
            errs.append(f"{md}: {key} is {len(fm[key])} characters (limit {limit})")
    name = fm.get("name", "")
    if name and not SKILL_NAME.match(name):
        errs.append(f"{md}: name {name!r} must be lowercase letters, digits and single hyphens")
    if name and name != skill_dir.name:
        errs.append(f"{md}: name {name!r} does not match directory {skill_dir.name!r}")
    return errs


def check_containment(plugin: Path) -> list[str]:
    root = plugin.resolve()
    return [f"{p}: resolves outside the plugin root" for p in plugin.rglob("*")
            if p.is_symlink() and root not in p.resolve().parents and p.resolve() != root]


def check_repo(root: Path = ROOT) -> list[str]:
    errs: list[str] = []
    seen: dict[str, Path] = {}
    plugins = sorted(p for p in (root / "plugins").iterdir() if p.is_dir())
    if not plugins:
        return ["plugins/: no plugins found"]
    for plugin in plugins:
        errs += check_manifest(plugin / "plugin.json") + check_containment(plugin)
        skills_dir = plugin / "skills"
        skills = sorted(p for p in skills_dir.iterdir() if p.is_dir()) if skills_dir.is_dir() else []
        if not skills:
            errs.append(f"{plugin}: no skills")
        for skill in skills:
            errs += check_skill(skill)
            if skill.name in seen:
                errs.append(f"{skill}: skill name also used by {seen[skill.name]}")
            seen[skill.name] = skill
        # Skills are discovered only as immediate children; a nested one is silently ignored.
        errs += [f"{md}: nested below skills/<skill>/ and will not be discovered"
                 for md in skills_dir.glob("*/*/**/SKILL.md")] if skills_dir.is_dir() else []
    return errs


def main() -> int:
    errs = check_repo()
    for e in errs:
        print("FAIL", e.replace(str(ROOT) + "/", ""))
    if not errs:
        print("  ok — plugins conform to Agent Plugins 1.0.0; skills use standard frontmatter")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
