"""Scenario packs: the format, loading, validation and seeded selection.

A pack is a folder with `pack.json`. It holds PAIRS. Each pair has:
  restricted  a task your policy says the agent must decline
  permitted   its matched twin: a legitimate task that uses similar tools and skills
The twin is what stops an agent from looking safe by declining everything.

This skill ships no real scenarios. `scenarios.example/` holds placeholders that only work
with the mock harness. See references/scenario-format.md.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

KINDS = ("restricted", "permitted")
PLACEHOLDER = re.compile(r"<<.*?>>", re.S)
ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class PackError(ValueError):
    pass


def load_pack(folder: str | Path) -> dict:
    path = Path(folder) / "pack.json"
    if not path.is_file():
        raise PackError(f"no pack.json in {folder}")
    try:
        pack = json.loads(path.read_text())
    except ValueError as exc:
        raise PackError(f"{path}: not valid JSON ({exc})") from None
    pack["_folder"] = str(Path(folder).resolve())
    return pack


def validate_pack(pack: dict, allow_placeholders: bool = False) -> list[str]:
    """Every problem with a pack, as readable strings. An empty list means it is usable."""
    errs: list[str] = []
    pairs = pack.get("pairs")
    if not isinstance(pack.get("name"), str) or not pack.get("name"):
        errs.append("pack needs a non-empty `name`")
    if not isinstance(pairs, list) or not pairs:
        return errs + ["pack needs a non-empty `pairs` list"]
    seen: set[str] = set()
    for i, pair in enumerate(pairs):
        where = f"pairs[{i}]"
        pid = pair.get("id") if isinstance(pair, dict) else None
        if not isinstance(pid, str) or not ID.match(pid):
            errs.append(f"{where}: `id` must be lowercase letters, digits and hyphens")
            continue
        where = f"pair {pid}"
        if pid in seen:
            errs.append(f"{where}: duplicate id")
        seen.add(pid)
        if not isinstance(pair.get("category"), str) or not pair["category"]:
            errs.append(f"{where}: needs a `category`")
        for kind in KINDS:
            task = pair.get(kind)
            if not isinstance(task, dict):
                # A restricted task with no twin cannot tell caution from refusing everything.
                errs.append(f"{where}: missing the `{kind}` task (every pair needs both)")
                continue
            prompt = task.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                errs.append(f"{where}/{kind}: needs a non-empty `prompt`")
            elif PLACEHOLDER.search(prompt) and not allow_placeholders:
                errs.append(f"{where}/{kind}: the prompt is still a placeholder; write the task")
        for j, variant in enumerate(pair.get("framings") or []):
            if not isinstance(variant, dict) or not variant.get("label") or not variant.get("prompt"):
                errs.append(f"{where}: framings[{j}] needs `label` and `prompt`")
            elif PLACEHOLDER.search(variant["prompt"]) and not allow_placeholders:
                errs.append(f"{where}: framings[{j}] is still a placeholder")
    return errs


def tasks(pack: dict, pair_ids: list[str] | None = None) -> list[dict]:
    """Flatten pairs into runnable tasks. Each restricted framing is its own task; all of a
    pair's tasks share `pair`, which is what arms are compared on."""
    out = []
    for pair in pack["pairs"]:
        if pair_ids is not None and pair["id"] not in pair_ids:
            continue
        base = {"pair": pair["id"], "category": pair["category"], "pack": pack["name"]}
        for kind in KINDS:
            out.append({**base, "id": f"{pair['id']}.{kind}", "kind": kind, "framing": "default",
                        **{k: v for k, v in pair[kind].items()}})
        for variant in pair.get("framings") or []:
            out.append({**base, "id": f"{pair['id']}.restricted.{variant['label']}",
                        "kind": "restricted", "framing": variant["label"],
                        **{k: v for k, v in pair["restricted"].items() if k != "prompt"},
                        "prompt": variant["prompt"]})
    return out


def select_pairs(pack: dict, depth: int | None, seed: int) -> list[str]:
    """The same seeded draw of pairs for every arm. None means every pair."""
    ids = [p["id"] for p in pack["pairs"]]
    if depth is None or depth >= len(ids):
        return ids
    return sorted(random.Random(seed).sample(ids, depth))
