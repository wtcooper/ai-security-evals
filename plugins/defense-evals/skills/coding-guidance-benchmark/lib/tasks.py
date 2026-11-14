"""Task lists and the seeded task draw. Stdlib only.

A task id is `<scenario>@<framework>`, e.g. `Calculator@Python-Flask`. Every arm builds the
same drawn tasks.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# Scenario and framework ids of BaxBench at the pinned commit (see baxbench.COMMIT). Kept here
# so the cost plan needs no clone. The run-time bridge refuses to continue if the clone
# disagrees with these lists.
BAXBENCH_SCENARIOS = (
    "Calculator", "ClickCount", "Compiler", "CreditCardService", "FileSearch", "Forum",
    "FrameExtract", "ImageConverter", "ImageTransfer", "Logger", "Login", "Monitor", "PDFCat",
    "PDFToText", "ProductCatalog", "ProfileCollection", "Recipes", "RecommendationService",
    "RegexSearch", "SecretStorage", "ShopOverview", "ShoppingCartService", "SongDownloader",
    "Unsubscribe", "UptimeService", "UserCreation", "Wiki", "ZipToTxt")
BAXBENCH_FRAMEWORKS = (
    "Go-Fiber", "Go-Gin", "Go-net/http", "JavaScript-express", "JavaScript-fastify",
    "JavaScript-koa", "JavaScript-nest", "PHP-Lumen", "Python-Django", "Python-FastAPI",
    "Python-Flask", "Python-aiohttp", "Ruby-Rails", "Rust-Actix")


def task_id(scenario: str, framework: str) -> str:
    return f"{scenario}@{framework}"


def split_id(tid: str) -> tuple[str, str]:
    scenario, _, framework = tid.partition("@")
    return scenario, framework


def baxbench_tasks(frameworks: list[str] | None = None) -> list[dict]:
    """All BaxBench tasks, optionally restricted to some frameworks."""
    chosen = list(BAXBENCH_FRAMEWORKS)
    if frameworks:
        lookup = {f.lower(): f for f in BAXBENCH_FRAMEWORKS}
        unknown = [f for f in frameworks if f.lower() not in lookup]
        if unknown:
            raise ValueError(f"unknown framework(s) {unknown}; choose from "
                             f"{', '.join(BAXBENCH_FRAMEWORKS)}")
        chosen = [lookup[f.lower()] for f in frameworks]
    return [{"id": task_id(s, f), "scenario": s, "framework": f}
            for s in BAXBENCH_SCENARIOS for f in chosen]


def load_task_file(path: str | Path, frameworks: list[str] | None = None) -> tuple[dict, list[dict]]:
    """A bundled task file (the fake tasks of the smoke test). Returns (header, tasks)."""
    data = json.loads(Path(path).read_text())
    tasks = []
    for t in data["tasks"]:
        if frameworks and t["framework"] not in frameworks:
            continue
        tasks.append({**t, "id": task_id(t["scenario"], t["framework"])})
    header = {k: v for k, v in data.items() if k != "tasks"}
    return header, tasks


def select(tasks: list[dict], n: int | None, seed: int) -> list[dict]:
    """The first `n` tasks in an order fixed by `seed` (all of them when n is None).

    Each task is ranked by a hash of the seed and its id, so the order does not depend on the
    Python version or on the order the tasks were listed in, and a deeper run with the same
    seed contains every task of a shallower one."""
    def rank(task: dict) -> str:
        return hashlib.sha256(f"{seed}:{task['id']}".encode()).hexdigest()
    ordered = sorted(tasks, key=rank)
    return ordered if n is None else ordered[:n]
