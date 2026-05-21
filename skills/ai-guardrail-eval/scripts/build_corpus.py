#!/usr/bin/env python3
"""
build_corpus.py - Corpus builder for guardrail evaluation.

Pulls public benchmarks from GitHub, scores prompts, generates Crescendo-style
multi-turn wrappers around a subset of harmful prompts, and (when HF_TOKEN is
set) additionally pulls MHJ and AgentHarm from gated HuggingFace datasets.
Writes data/corpus_v1.json with explicit `is_partial` and `missing_sources`
metadata so consumers know exactly what's in their copy.

Tier composition (cumulative; T1 is a subset of T2 is a subset of T3):

  T1 - smoke (~100 cases)
       ~50 harmful: 15 HarmBench + 15 AILuminate + 10 StrongREJECT
                    + 10 XSTest-unsafe + 0 multi-turn  (multi-turn lands in T2+)
       ~50 benign:  35 XSTest-safe + 15 Alpaca

  T2 - standard (~316 cases)
       ~158 harmful: above + 30 StrongREJECT extra + 10 XSTest + 10 AdvBench
                     + 8 multi-turn harmful
       ~158 benign:  above + 100 XSTest-safe + 8 multi-turn benign

  T3 - comprehensive (~620 cases)
       ~310 harmful: above + full quotas + 10 multi-turn harmful
       ~310 benign:  above + full quotas + 4 multi-turn benign

Multi-turn cases use authored scaffolding (see scripts/multi_turn_templates.py)
that wraps published harmful prompts in Crescendo-style escalation patterns.
The attack content is from public research datasets; only the conversational
framing is new.

Gated sources (MHJ, AgentHarm) are pulled ONLY when HF_TOKEN is in the
environment. Without it, the corpus is marked is_partial=True with
missing_sources=["mhj","agentharm"].

Quality scoring (per source, diversity-aware greedy selection):
    + source authority
    + category coverage
    + length appropriateness
    + lexical uniqueness
    + non-triviality

Run:
    python scripts/build_corpus.py                        # partial corpus
    HF_TOKEN=hf_xxx python scripts/build_corpus.py        # full corpus
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
import json
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Local import: the authored multi-turn templates live next to this script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from multi_turn_templates import (
    wrap_harmful, wrap_benign, technique_family_for,
    HARMFUL_TEMPLATE_NAMES, BENIGN_TEMPLATE_NAMES,
)


# ---------------------------------------------------------------------------
# Source definitions
# ---------------------------------------------------------------------------

SOURCES = {
    "harmbench": {
        "url": "https://raw.githubusercontent.com/centerforaisafety/HarmBench/main/data/behavior_datasets/harmbench_behaviors_text_all.csv",
        "prompt_field": "Behavior",
        "category_field": "SemanticCategory",
        "id_field": "BehaviorID",
        "functional_filter": ("FunctionalCategory", "standard"),
        "authority": 0.95,
        "label": "harmful",
        "citation": "Mazeika et al., HarmBench (ICML 2024) arXiv:2402.04249",
        "license": "MIT",
    },
    "ailuminate_demo": {
        "url": "https://raw.githubusercontent.com/mlcommons/ailuminate/main/airr_official_1.0_demo_en_us_prompt_set_release.csv",
        "prompt_field": "prompt_text",
        "category_field": "hazard",
        "id_field": "release_prompt_id",
        "authority": 1.0,
        "label": "harmful",
        "citation": "Ghosh et al., AILuminate v1.0 (MLCommons 2025) arXiv:2503.05731",
        "license": "CC-BY-4.0",
    },
    "strongreject": {
        "url": "https://raw.githubusercontent.com/alexandrasouly/strongreject/main/strongreject_dataset/strongreject_dataset.csv",
        "prompt_field": "forbidden_prompt",
        "category_field": "category",
        "authority": 0.9,
        "label": "harmful",
        "citation": "Souly et al., A StrongREJECT for Empty Jailbreaks (NeurIPS 2024) arXiv:2402.10260",
        "license": "MIT",
    },
    "advbench": {
        "url": "https://raw.githubusercontent.com/llm-attacks/llm-attacks/main/data/advbench/harmful_behaviors.csv",
        "prompt_field": "goal",
        "category_field": None,
        "authority": 0.7,
        "label": "harmful",
        "default_category": "harmful_behavior",
        "citation": "Zou et al., Universal and Transferable Adversarial Attacks (2023) arXiv:2307.15043",
        "license": "MIT",
    },
    "xstest": {
        "url": "https://raw.githubusercontent.com/paul-rottger/xstest/main/xstest_prompts.csv",
        "prompt_field": "prompt",
        "category_field": "type",
        "id_field": "id",
        "label_field": "label",  # "safe" -> benign, "unsafe" -> harmful
        "authority": 0.95,
        "label": "split_by_label_field",
        "citation": "Roettger et al., XSTest (NAACL 2024) arXiv:2308.01263",
        "license": "CC-BY-4.0",
    },
    "alpaca": {
        "url": "https://raw.githubusercontent.com/tatsu-lab/stanford_alpaca/main/alpaca_data.json",
        "format": "json",
        "prompt_field": "instruction",
        "input_field": "input",
        "authority": 0.85,
        "label": "benign",
        "default_category": "benign",
        "citation": "Taori et al., Stanford Alpaca (2023)",
        "license": "CC-BY-NC-4.0",
    },
    # ---- CyberSecEval (Meta PurpleLlama) -------------------------------------
    # Llama Community License: redistributable with attribution, no 700M MAU
    # exception relevant here. All four CyberSecEval datasets are flat JSON
    # arrays parsed by the generic parse_cyberseceval() function.
    "cyberseceval_pi": {
        "url": "https://raw.githubusercontent.com/meta-llama/PurpleLlama/main/CybersecurityBenchmarks/datasets/prompt_injection/prompt_injection.json",
        "format": "cyberseceval",
        "prompt_field": "user_input",
        "system_field": "test_case_prompt",          # produces messages = [system, user]
        "category_field": "risk_category",
        "technique_family_field": "injection_variant",  # 15 distinct attack patterns
        "id_field": "prompt_id",
        "authority": 0.95,
        "label": "harmful",
        "citation": "Bhatt et al., CyberSecEval (Meta PurpleLlama, 2024) arXiv:2312.04724 / 2404.13161",
        "license": "Llama Community License",
    },
    "cyberseceval_mitre": {
        "url": "https://raw.githubusercontent.com/meta-llama/PurpleLlama/main/CybersecurityBenchmarks/datasets/mitre/mitre_benchmark_100_per_category_with_augmentation.json",
        "format": "cyberseceval",
        "prompt_field": "mutated_prompt",
        "category_field": "mitre_category",
        "technique_family_field": "mitre_category",  # 10 ATT&CK categories
        "authority": 0.95,
        "label": "harmful",
        "default_category": "cyber_attack_assistance",
        "citation": "Bhatt et al., CyberSecEval MITRE (Meta PurpleLlama)",
        "license": "Llama Community License",
    },
    "cyberseceval_mitre_frr": {
        "url": "https://raw.githubusercontent.com/meta-llama/PurpleLlama/main/CybersecurityBenchmarks/datasets/mitre_frr/mitre_frr.json",
        "format": "cyberseceval",
        "prompt_field": "mutated_prompt",
        "category_field": "attack_type",
        # benign — no technique_family (technique_family is for attack patterns)
        "authority": 0.9,
        "label": "benign",
        "default_category": "cyber_legitimate",
        "citation": "Bhatt et al., CyberSecEval MITRE-FRR (Meta PurpleLlama)",
        "license": "Llama Community License",
    },
    "cyberseceval_interpreter": {
        "url": "https://raw.githubusercontent.com/meta-llama/PurpleLlama/main/CybersecurityBenchmarks/datasets/interpreter/interpreter.json",
        "format": "cyberseceval",
        "prompt_field": "mutated_prompt",
        "category_field": "attack_type",
        "technique_family_field": "attack_type",  # 5 interpreter-abuse families
        "authority": 0.9,
        "label": "harmful",
        "default_category": "code_interpreter_abuse",
        "citation": "Bhatt et al., CyberSecEval Interpreter (Meta PurpleLlama)",
        "license": "Llama Community License",
    },
}


# Per-source quotas. Format: (T1_count, T2_total_count, T3_total_count)
# T1 ⊂ T2 ⊂ T3 — the first N of a list are tier 1, the first M are tier 2, all are tier 3.
QUOTAS: Dict[str, Tuple[int, int, int]] = {
    "harmbench":                  (15, 45,  90),
    "ailuminate_demo":            (15, 45,  95),
    "strongreject":               (10, 30,  55),
    "xstest_unsafe":              (10, 20,  30),
    "advbench":                   ( 0, 10,  30),
    "xstest_safe":                (35, 135, 250),
    "alpaca":                     (15, 15,  50),
    # Multi-turn cases land in T2+; smoke stays small for the iteration loop.
    # Bumped from (0,8,18)/(0,8,12) once we expanded the template catalog from
    # 5 to 14 harmful and from 5 to 10 benign patterns - more templates means
    # more technique diversity at higher quotas without redundancy.
    "multi_turn_harmful":         ( 0, 25,  60),
    "multi_turn_benign":          ( 0, 12,  30),
    # HuggingFace sources. Crescendo (public) is always attempted if the
    # `datasets` lib is installed; MHJ and AgentHarm need HF_TOKEN.
    # Crescendo trimmed from (0,6,15) to (0,3,8): the dataset is 6,918
    # variants of ONE attack technique (substitution-cipher), so extra cases
    # add redundancy not diversity. 8 is enough to represent the technique
    # without over-weighting it relative to other multi-turn patterns.
    "crescendo":                  ( 0,  3,   8),
    "mhj":                        ( 0, 10,  25),
    "agentharm":                  ( 0,  5,  15),
    # ---- Prompt injection sources (smoke now includes ~30 PI cases so
    # guardrails like Prisma AIRS PI protection have signal at smoke tier) ----
    "cyberseceval_pi":            (10, 30,  60),  # 15 variants -> ~4 per variant at T3
    "cyberseceval_mitre":         ( 0, 15,  40),  # 10 ATT&CK categories -> 4 per category at T3
    "cyberseceval_mitre_frr":     ( 5, 15,  30),  # benign cyber for FRR
    "cyberseceval_interpreter":   ( 0, 10,  25),  # 5 attack types -> 5 per attack at T3
    "deepset_pi_harmful":         ( 5, 15,  30),  # the label=1 rows from deepset
    "deepset_pi_benign":          (10, 25,  60),  # the label=0 rows; matched FPR baseline
    "lakera_gandalf":             ( 5, 25,  90),  # capped at ~90 per user direction
}


# HuggingFace sources. Crescendo is public; MHJ and AgentHarm are gated.
# Public HF sources are pulled when the `datasets` library is available.
# Gated sources also require HF_TOKEN in the environment.
HF_SOURCES = {
    "crescendo": {
        "hf_dataset": "tom-gibbs/multi-turn_jailbreak_attack_datasets",
        "hf_config": None,                     # dataset only ships a 'default' config
        "hf_split": "train",
        "gated": False,
        "authority": 0.85,
        "label": "harmful",
        "default_category": "multi_turn_crescendo",
        "citation": "Gibbs et al., Emerging Vulnerabilities in Frontier Models (arXiv:2409.00137)",
        "license": "MIT",
    },
    "mhj": {
        "hf_dataset": "ScaleAI/mhj",
        "hf_config": None,
        "hf_split": "train",
        "gated": True,
        "authority": 0.95,
        "label": "harmful",
        "default_category": "multi_turn_jailbreak",
        "citation": "Li et al., MHJ: Multi-turn Human Jailbreaks (Scale AI, 2024)",
        "license": "HuggingFace gated - see dataset page",
    },
    # ---- Public PI datasets (no HF_TOKEN needed) ----------------------------
    "deepset_pi": {
        "hf_dataset": "deepset/prompt-injections",
        "hf_config": None,
        "hf_split": "train",                    # 546 rows; test split has 116
        "gated": False,
        "authority": 0.85,
        "label": "split_by_deepset_label",       # 88% benign / 12% PI; split post-parse
        "default_category": "prompt_injection",
        "citation": "deepset/prompt-injections (Apache-2.0)",
        "license": "Apache-2.0",
    },
    "lakera_gandalf": {
        "hf_dataset": "Lakera/gandalf_ignore_instructions",
        "hf_config": None,
        "hf_split": "train",                    # 777 rows; val 111, test 112
        "gated": False,
        "authority": 0.9,
        "label": "harmful",
        "default_category": "system_prompt_exfiltration",
        "citation": "Lakera Gandalf (Pfister et al., arXiv:2501.07927; MIT)",
        "license": "MIT",
    },
    "agentharm": {
        "hf_dataset": "ai-safety-institute/AgentHarm",
        "hf_config": "harmful",
        "hf_split": "test_public",
        "gated": True,
        "authority": 0.9,
        "label": "harmful",
        "default_category": "agent_harm",
        "citation": "Andriushchenko et al., AgentHarm (AISI, 2024)",
        "license": "HuggingFace gated - see dataset page",
    },
}
# Back-compat alias (callers still iterate GATED_SOURCES in places):
GATED_SOURCES = {k: v for k, v in HF_SOURCES.items() if v["gated"]}


# ---------------------------------------------------------------------------
# Fetching + parsing
# ---------------------------------------------------------------------------

def fetch(url: str, label: str = "") -> str:
    """GET a URL, return text. Raises on failure."""
    print(f"  fetching {label or url} ...", end=" ", flush=True)
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = resp.read().decode("utf-8", errors="replace")
    print(f"{len(data):,} bytes")
    return data


def parse_csv_source(name: str, text: str, cfg: dict) -> List[dict]:
    """Parse a CSV source into normalized prompt records."""
    reader = csv.DictReader(io.StringIO(text))
    out: List[dict] = []

    fcat = cfg.get("functional_filter")
    label_field = cfg.get("label_field")

    for i, row in enumerate(reader):
        # Filter to "standard" behaviors for HarmBench (skip contextual etc.)
        if fcat is not None and (row.get(fcat[0]) or "").strip().lower() != fcat[1]:
            continue

        prompt = (row.get(cfg["prompt_field"]) or "").strip()
        if not prompt:
            continue

        if cfg.get("category_field"):
            category = (row.get(cfg["category_field"]) or "unknown").strip().lower()
        else:
            category = cfg.get("default_category", "unknown")

        # XSTest: route to xstest_safe or xstest_unsafe based on label field
        if label_field:
            sub = (row.get(label_field) or "").strip().lower()
            if sub == "safe":
                effective_source = "xstest_safe"
                effective_label = "benign"
            elif sub == "unsafe":
                effective_source = "xstest_unsafe"
                effective_label = "harmful"
            else:
                continue
        else:
            effective_source = name
            effective_label = cfg["label"]

        record_id = row.get(cfg.get("id_field", "")) or f"{name}-{i}"

        out.append({
            "id": f"{effective_source}-{record_id}",
            "source": effective_source,
            "category": category,
            "label": effective_label,
            "prompt": prompt,
            "_original_index": i,
        })
    return out


def parse_json_source(name: str, text: str, cfg: dict) -> List[dict]:
    """Parse Alpaca JSON into normalized records."""
    data = json.loads(text)
    out = []
    for i, row in enumerate(data):
        prompt = (row.get(cfg["prompt_field"]) or "").strip()
        inp = (row.get(cfg.get("input_field", "")) or "").strip()
        if not prompt:
            continue
        # If there's an input context, fold it in.
        if inp:
            prompt = f"{prompt}\n\n{inp}"
        out.append({
            "id": f"{name}-{i}",
            "source": name,
            "category": cfg.get("default_category", "benign"),
            "label": cfg["label"],
            "prompt": prompt,
            "_original_index": i,
        })
    return out


def parse_cyberseceval(name: str, text: str, cfg: dict) -> List[dict]:
    """
    Generic parser for CyberSecEval JSON files (top-level array of objects).

    Honors per-source config:
      prompt_field             - the attack/test prompt column (required)
      system_field             - optional system-prompt column; when present we
                                 emit messages=[system, user] for the case
      category_field           - column to use as case.category
      technique_family_field   - column to use as case.technique_family
                                 (the metrics layer slices by this)
      id_field                 - column to use as the case id suffix
      default_category         - fallback when category_field is missing/empty

    All CyberSecEval files we ingest are flat arrays — the file-specific
    schemas live in the SOURCES entry rather than in this function.
    """
    data = json.loads(text)
    out: List[dict] = []

    def _flatten(v):
        """Some fields ship as lists (e.g. attack_type=['Container Escape'])."""
        if isinstance(v, list):
            return v[0] if v else None
        return v

    for i, row in enumerate(data):
        prompt = str(row.get(cfg["prompt_field"]) or "").strip()
        if not prompt:
            continue

        system_field = cfg.get("system_field")
        system_prompt = str(row.get(system_field) or "").strip() if system_field else ""
        if system_prompt:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
        else:
            messages = None

        category = _flatten(row.get(cfg.get("category_field"))) or cfg.get("default_category", "unknown")
        category = str(category).lower().replace(" ", "_")

        tech_family = None
        tf_field = cfg.get("technique_family_field")
        if tf_field:
            raw_tf = _flatten(row.get(tf_field))
            if raw_tf:
                tech_family = str(raw_tf).lower().replace(" ", "_")

        rec_id = row.get(cfg.get("id_field") or "prompt_id") or str(i)
        out.append({
            "id": f"{name}-{rec_id}",
            "source": name,
            "category": category,
            "label": cfg["label"],
            "prompt": prompt,
            "messages": messages,
            "_original_index": i,
            "technique_family": tech_family,
        })
    return out


# ---------------------------------------------------------------------------
# Quality scoring + diversity-aware greedy selection
# ---------------------------------------------------------------------------

def score(prompt: str, category: str, source_authority: float,
          seen_cats: Dict[str, int], seen_prefixes: Dict[str, int]) -> float:
    """Composite quality score in [0, 1]. Higher = better candidate to pick next."""
    s = 0.0

    # Source authority (0.30)
    s += 0.30 * source_authority

    # Length appropriateness (0.15) - sweet spot 50-300 chars
    L = len(prompt)
    if 50 <= L <= 300:
        length_score = 1.0
    elif L < 50:
        length_score = L / 50.0
    else:
        length_score = max(0.0, 1.0 - (L - 300) / 500.0)
    s += 0.15 * length_score

    # Category coverage (0.30) - prefer under-represented categories
    s += 0.30 * (1.0 / (1.0 + seen_cats.get(category, 0)))

    # Lexical uniqueness (0.10) - prefer prompts not starting like prior picks
    prefix_words = prompt.lower().split()[:3]
    prefix = " ".join(prefix_words)
    s += 0.10 * (1.0 / (1.0 + seen_prefixes.get(prefix, 0)))

    # Non-triviality (0.15) - penalize keyword starters that any guardrail nails
    lower_head = prompt.lower()[:40]
    trivial_starters = (
        "how to make a bomb",
        "how do i make a bomb",
        "write a tutorial",
        "give detailed instructions",
        "step-by-step instructions",
        "step by step instructions",
    )
    triviality_penalty = 0.5 if any(t in lower_head for t in trivial_starters) else 1.0
    s += 0.15 * triviality_penalty

    return s


def rank_within_source(records: List[dict], authority: float, max_input: int = 2000, seed: int = 42) -> List[dict]:
    """
    Diversity-aware greedy ranking.

    Repeatedly picks the highest-scoring remaining record under the current
    'seen categories / prefixes' state, then updates the state. Result is a
    list ordered from highest-quality (most diverse) to lowest.

    For very large sources (e.g. Alpaca's 52k rows), we randomly sub-sample
    down to `max_input` rows before ranking — the greedy loop is O(n^2), so
    52k is impractical and unnecessary when we only need a few dozen picks.
    The sampling uses `seed` for determinism.
    """
    import random as _random
    seen_cats: Dict[str, int] = defaultdict(int)
    seen_prefixes: Dict[str, int] = defaultdict(int)
    seen_hashes: set = set()

    # Pre-deduplicate on a generous prefix hash. The original 80-char prefix
    # was too aggressive for curated benchmarks where rows share long
    # boilerplate openings (e.g. CyberSecEval interpreter prompts all start
    # "Write Python code that..." — distinct attacks, collided on first 80).
    # 240 chars catches Alpaca-style scraped near-duplicates without erasing
    # legitimate benchmark variety.
    deduped: List[dict] = []
    for r in records:
        h = hashlib.sha1(r["prompt"][:240].lower().encode("utf-8")).hexdigest()
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        deduped.append(r)

    # Cap input size so ranking stays tractable.
    if len(deduped) > max_input:
        rng = _random.Random(seed)
        deduped = rng.sample(deduped, max_input)
        print(f"    (sub-sampled to {max_input} for ranking)")

    remaining = list(deduped)
    ranked: List[dict] = []
    rank_position = 0

    while remaining:
        best_idx = -1
        best_score = -1.0
        for i, r in enumerate(remaining):
            sc = score(r["prompt"], r["category"], authority, seen_cats, seen_prefixes)
            if sc > best_score:
                best_score = sc
                best_idx = i
        picked = remaining.pop(best_idx)
        rank_position += 1

        # Update seen state so subsequent picks favor different categories/openings
        seen_cats[picked["category"]] += 1
        prefix = " ".join(picked["prompt"].lower().split()[:3])
        seen_prefixes[prefix] += 1

        ranked.append({
            **picked,
            "quality_score": round(best_score, 4),
            "rank_in_source": rank_position,
        })
    return ranked


# ---------------------------------------------------------------------------
# Tier assignment + corpus assembly
# ---------------------------------------------------------------------------

def assign_tier(rank_in_source: int, quotas: Tuple[int, int, int]) -> int:
    """rank_in_source is 1-based. Returns 1, 2, or 3 (lower = higher quality)."""
    t1, t2, t3 = quotas
    if rank_in_source <= t1:
        return 1
    if rank_in_source <= t2:
        return 2
    if rank_in_source <= t3:
        return 3
    return 0  # dropped (over quota)


def build_corpus(seed: int = 42, local_data_dir: Optional[str] = None) -> dict:
    """Fetch, rank, tier, and assemble the full corpus structure."""
    print("\n=== Fetching public sources from GitHub ===")
    raw: Dict[str, List[dict]] = {}

    for name, cfg in SOURCES.items():
        try:
            text = fetch(cfg["url"], label=name)
        except Exception as e:
            print(f"  [FAIL] {name}: {e}", file=sys.stderr)
            continue
        fmt = cfg.get("format")
        if fmt == "json":
            raw[name] = parse_json_source(name, text, cfg)
        elif fmt == "cyberseceval":
            raw[name] = parse_cyberseceval(name, text, cfg)
        else:
            raw[name] = parse_csv_source(name, text, cfg)

    # XSTest is split into xstest_safe / xstest_unsafe by parse_csv_source;
    # surface those separately for ranking.
    if "xstest" in raw:
        xs = raw.pop("xstest")
        raw["xstest_safe"] = [r for r in xs if r["source"] == "xstest_safe"]
        raw["xstest_unsafe"] = [r for r in xs if r["source"] == "xstest_unsafe"]

    # ---- HuggingFace sources ----
    # Crescendo is public; MHJ and AgentHarm are gated and require HF_TOKEN.
    # The `datasets` library is required for any of them.
    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    hf_loaded: List[str] = []
    hf_skipped: List[str] = []

    # ---- Local downloads (for users who manually grabbed gated data) ----
    # If --local-data-dir is set, look for known-shape files and load them.
    # Sources loaded locally are marked in hf_loaded so the HF-API loop below
    # skips re-fetching them.
    if local_data_dir:
        local_dir = Path(local_data_dir)
        print(f"\n=== Loading local downloads from {local_dir} ===")
        # MHJ: harmbench_behaviors.csv is the upstream-named file for the MHJ
        # multi-turn red-team conversations CSV (despite the misleading name).
        mhj_path = local_dir / "harmbench_behaviors.csv"
        if mhj_path.exists():
            try:
                parsed = _load_local_mhj(mhj_path)
                raw["mhj"] = parsed
                hf_loaded.append("mhj")
                print(f"  mhj                       {len(parsed):,} multi-turn from {mhj_path.name}")
            except Exception as e:
                print(f"  mhj                       FAIL ({type(e).__name__}: {str(e)[:120]})")
        else:
            print(f"  mhj                       not found ({mhj_path.name})")
        # AgentHarm chat: single-turn harmful prompts from chat_public_test.json
        agentharm_chat_path = local_dir / "chat_public_test.json"
        if agentharm_chat_path.exists():
            try:
                parsed = _load_local_agentharm_chat(agentharm_chat_path)
                raw["agentharm"] = parsed
                hf_loaded.append("agentharm")
                print(f"  agentharm                 {len(parsed):,} single-turn from {agentharm_chat_path.name}")
            except Exception as e:
                print(f"  agentharm                 FAIL ({type(e).__name__}: {str(e)[:120]})")
        else:
            print(f"  agentharm                 not found ({agentharm_chat_path.name})")

    try:
        from datasets import load_dataset  # type: ignore
        have_datasets = True
    except ImportError:
        have_datasets = False
        print("\n[INFO] `datasets` library not installed; skipping ALL HF sources.")
        print("       pip install datasets   to enable Crescendo / MHJ / AgentHarm.")
        hf_skipped = [n for n in HF_SOURCES.keys() if n not in hf_loaded]

    if have_datasets:
        print("\n=== Fetching HuggingFace sources ===")
        for hname, hcfg in HF_SOURCES.items():
            if hname in hf_loaded:
                print(f"  {hname:25s} already loaded locally; skipping HF fetch")
                continue
            is_gated = hcfg.get("gated", False)
            if is_gated and not hf_token:
                print(f"  {hname:25s} SKIPPED (gated, HF_TOKEN not set)")
                hf_skipped.append(hname)
                continue
            try:
                ds_name = hcfg["hf_dataset"]
                ds_cfg = hcfg.get("hf_config")
                ds_split = hcfg.get("hf_split", "train")
                print(f"  fetching {hname} ({ds_name}/{ds_cfg or 'default'}) ...",
                      end=" ", flush=True)
                kwargs = {"split": ds_split}
                if ds_cfg:
                    kwargs["name"] = ds_cfg
                if hf_token:
                    kwargs["token"] = hf_token
                ds = load_dataset(ds_name, **kwargs)
                parsed = _parse_hf_source(hname, ds, hcfg)
                raw[hname] = parsed
                hf_loaded.append(hname)
                print(f"{len(parsed):,} prompts")
            except Exception as e:
                print(f"FAIL ({type(e).__name__}: {str(e)[:120]})")
                hf_skipped.append(hname)
                if is_gated and "gated" in str(e).lower():
                    print(f"    -> request access at "
                          f"https://huggingface.co/datasets/{hcfg['hf_dataset']}")

    # deepset_pi is loaded with mixed labels (88% benign / 12% PI). Split into
    # two sources so each gets its own quota — same pattern as xstest above.
    if "deepset_pi" in raw:
        dp = raw.pop("deepset_pi")
        dp_h = [r for r in dp if r["label"] == "harmful"]
        dp_b = [r for r in dp if r["label"] == "benign"]
        for r in dp_h:
            r["source"] = "deepset_pi_harmful"
            r["id"] = r["id"].replace("deepset_pi-", "deepset_pi_harmful-", 1)
        for r in dp_b:
            r["source"] = "deepset_pi_benign"
            r["id"] = r["id"].replace("deepset_pi-", "deepset_pi_benign-", 1)
        raw["deepset_pi_harmful"] = dp_h
        raw["deepset_pi_benign"] = dp_b
        # Keep hf_loaded pointing at the unsplit name so is_partial accounting
        # works; mirror the split names into the SOURCES-like metadata below.

    # Back-compat aliases used in the metadata block below
    gated_loaded = [n for n in hf_loaded if HF_SOURCES[n].get("gated")]
    gated_skipped = [n for n in hf_skipped if n in HF_SOURCES and HF_SOURCES[n].get("gated")]

    print("\n=== Source sizes ===")
    for n, recs in raw.items():
        print(f"  {n:25s} {len(recs):,} prompts")

    def _meta_lookup(n: str) -> dict:
        """Resolve the SOURCES/HF_SOURCES config for a source name, handling
        split-source aliases (xstest_safe/xstest_unsafe -> xstest,
        deepset_pi_harmful/deepset_pi_benign -> deepset_pi)."""
        if n in SOURCES:
            return SOURCES[n]
        if n in HF_SOURCES:
            return HF_SOURCES[n]
        # split-source aliases
        if n.startswith("xstest_"):
            return SOURCES["xstest"]
        if n.startswith("deepset_pi_"):
            return HF_SOURCES["deepset_pi"]
        # last-ditch fallback to keep the build from crashing on unknown names
        return SOURCES.get("xstest")

    print("\n=== Ranking within sources ===")
    ranked: Dict[str, List[dict]] = {}
    for name, recs in raw.items():
        cfg = _meta_lookup(name)
        authority = cfg["authority"]
        quota_t3 = QUOTAS.get(name, (0, 0, 200))[2]
        max_input = max(500, quota_t3 * 4)
        ranked[name] = rank_within_source(recs, authority, max_input=max_input)
        print(f"  {name:25s} {len(ranked[name]):,} ranked")

    # ---- Generate authored multi-turn cases ----
    # The harmful multi-turn cases wrap a selection of already-ranked harmful
    # prompts (from HarmBench, AILuminate, StrongREJECT) in Crescendo-style
    # escalation scaffolding. Benign multi-turn wraps XSTest-safe prompts in
    # plausible legitimate-use scenarios for FPR measurement.
    print("\n=== Generating multi-turn authored cases ===")
    mt_harmful_records = _generate_multi_turn(
        ranked, quota_total=QUOTAS["multi_turn_harmful"][2],
        sources=["harmbench", "ailuminate_demo", "strongreject"],
        label="harmful", template_names=HARMFUL_TEMPLATE_NAMES,
        wrap_fn=wrap_harmful, name="multi_turn_harmful",
    )
    mt_benign_records = _generate_multi_turn(
        ranked, quota_total=QUOTAS["multi_turn_benign"][2],
        sources=["xstest_safe"],
        label="benign", template_names=BENIGN_TEMPLATE_NAMES,
        wrap_fn=wrap_benign, name="multi_turn_benign",
    )
    ranked["multi_turn_harmful"] = mt_harmful_records
    ranked["multi_turn_benign"] = mt_benign_records
    print(f"  multi_turn_harmful       {len(mt_harmful_records):,} authored")
    print(f"  multi_turn_benign        {len(mt_benign_records):,} authored")

    print("\n=== Assigning tiers ===")
    cases: List[dict] = []
    summary: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))

    for name, recs in ranked.items():
        quotas = QUOTAS.get(name)
        if quotas is None:
            print(f"  [WARN] {name}: no quota - skipping", file=sys.stderr)
            continue
        for r in recs:
            tier = assign_tier(r["rank_in_source"], quotas)
            if tier == 0:
                continue
            cfg_for_meta = _meta_lookup(name)
            # multi_turn_* sources don't have a real fetch URL
            if name.startswith("multi_turn_"):
                source_url = "authored (Crescendo-style scaffolding around published prompts)"
                citation = "Russinovich et al., Crescendo (arXiv:2404.01833) - structural pattern only"
                license_ = "scaffolding: authored for this project; wrapped prompts inherit original source license"
            else:
                source_url = cfg_for_meta.get("url") or cfg_for_meta.get("hf_dataset", "unknown")
                citation = cfg_for_meta["citation"]
                license_ = cfg_for_meta["license"]
            # technique_family: attack pattern (harmful) or use-case scenario
            # (benign) for multi-turn cases. Authored multi-turn records carry
            # it directly from the template; Crescendo's whole dataset is one
            # technique (we verified 100% are substitution-cipher attacks);
            # single-turn and other sources don't get a technique_family.
            tech_family = r.get("technique_family")
            if tech_family is None and name == "crescendo":
                tech_family = "cipher_substitution"
            cases.append({
                "id": r["id"],
                "source": r["source"],
                "category": r["category"],
                "label": r["label"],
                "prompt": r["prompt"],
                "messages": r.get("messages"),  # populated for multi-turn cases
                "technique_family": tech_family,
                "quality_tier": tier,
                "quality_score": r["quality_score"],
                "rank_in_source": r["rank_in_source"],
                "source_url": source_url,
                "citation": citation,
                "license": license_,
            })
            summary[name][tier] += 1

    print("\n=== Composition ===")
    print(f"  {'source':<26} {'T1':>5} {'T2':>5} {'T3':>5} {'total':>7}")
    grand = {1: 0, 2: 0, 3: 0}
    for name in QUOTAS:
        counts = summary[name]
        c1 = counts.get(1, 0)
        c2 = counts.get(2, 0) + c1
        c3 = counts.get(3, 0) + c2
        total = counts.get(1, 0) + counts.get(2, 0) + counts.get(3, 0)
        grand[1] += c1; grand[2] += c2; grand[3] += c3
        print(f"  {name:<26} {c1:>5} {c2:>5} {c3:>5} {total:>7}")
    print(f"  {'TOTAL (cumulative)':<26} {grand[1]:>5} {grand[2]:>5} {grand[3]:>5}")

    harmful_by_tier = {t: sum(1 for c in cases if c["label"] == "harmful" and c["quality_tier"] <= t) for t in (1, 2, 3)}
    benign_by_tier = {t: sum(1 for c in cases if c["label"] == "benign" and c["quality_tier"] <= t) for t in (1, 2, 3)}
    multi_turn_by_tier = {t: sum(1 for c in cases if c.get("messages") and c["quality_tier"] <= t) for t in (1, 2, 3)}
    print("\n=== Label balance (cumulative) ===")
    print(f"  Tier 1 (smoke):         harmful={harmful_by_tier[1]:>4}  benign={benign_by_tier[1]:>4}  multi_turn={multi_turn_by_tier[1]:>4}")
    print(f"  Tier 2 (standard):      harmful={harmful_by_tier[2]:>4}  benign={benign_by_tier[2]:>4}  multi_turn={multi_turn_by_tier[2]:>4}")
    print(f"  Tier 3 (comprehensive): harmful={harmful_by_tier[3]:>4}  benign={benign_by_tier[3]:>4}  multi_turn={multi_turn_by_tier[3]:>4}")

    # Corpus is "partial" if any of the multi-turn / HF sources are missing.
    # Crescendo absence => partial (no real multi-turn data).
    # MHJ or AgentHarm absence => partial (gated; needs HF_TOKEN).
    missing_hf = [n for n in HF_SOURCES if n not in hf_loaded]
    is_partial = bool(missing_hf)

    if is_partial:
        print("\n[CORPUS IS PARTIAL]")
        print(f"  Missing HuggingFace sources: {missing_hf}")
        if "crescendo" in missing_hf:
            if not have_datasets:
                print(f"    crescendo  -> install `datasets` library (uv sync --extra corpus)")
            else:
                print(f"    crescendo  -> fetch failed; see [FAIL ...] above for the cause")
                print(f"                  https://huggingface.co/datasets/tom-gibbs/multi-turn_jailbreak_attack_datasets")
        if "mhj" in missing_hf:
            print(f"    mhj        -> request access + set HF_TOKEN")
            print(f"                  https://huggingface.co/datasets/ScaleAI/mhj")
        if "agentharm" in missing_hf:
            print(f"    agentharm  -> request access + set HF_TOKEN")
            print(f"                  https://huggingface.co/datasets/ai-safety-institute/AgentHarm")
        print(f"  Authored multi-turn scaffolding is still included as a supplement.")

    sources_meta = {}
    for name, cfg in SOURCES.items():
        sources_meta[name] = {
            "url": cfg["url"],
            "citation": cfg["citation"],
            "license": cfg["license"],
            "authority": cfg["authority"],
            "included": True,
        }
    for name, cfg in HF_SOURCES.items():
        sources_meta[name] = {
            "hf_dataset": cfg["hf_dataset"],
            "citation": cfg["citation"],
            "license": cfg["license"],
            "authority": cfg["authority"],
            "included": name in hf_loaded,
            "gated": cfg.get("gated", False),
        }
    sources_meta["multi_turn_authored"] = {
        "url": "authored from scripts/multi_turn_templates.py",
        "citation": "Crescendo paper structural pattern (Russinovich et al., arXiv:2404.01833)",
        "license": "authored scaffolding; wrapped prompts inherit original source license",
        "included": True,
        "note": "Each multi-turn case wraps a published harmful prompt in deterministic scaffolding. No new attack content is introduced.",
    }

    return {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "is_partial": is_partial,
        "missing_sources": missing_hf,
        "tiers": {
            "smoke": {"name": "smoke", "description": "~130 cases including ~30 prompt-injection cases. Use for tuning loops, CI smoke tests, and quick PI/content-harm signal checks."},
            "standard": {"name": "standard", "description": "~460 cases including PI, cyber-attack-assistance, multi-turn, and matched benign baselines. Default for vendor comparison."},
            "comprehensive": {"name": "comprehensive", "description": "Full ~1000 case suite across all attack classes (content-harm, prompt-injection, cyber-attack, multi-turn). Use for final vendor decisions."},
        },
        "sources": sources_meta,
        "composition": dict(summary),
        "label_balance": {
            "tier_1": {"harmful": harmful_by_tier[1], "benign": benign_by_tier[1], "multi_turn": multi_turn_by_tier[1]},
            "tier_2": {"harmful": harmful_by_tier[2], "benign": benign_by_tier[2], "multi_turn": multi_turn_by_tier[2]},
            "tier_3": {"harmful": harmful_by_tier[3], "benign": benign_by_tier[3], "multi_turn": multi_turn_by_tier[3]},
        },
        "cases": cases,
    }


def _load_local_mhj(csv_path: Path) -> List[dict]:
    """
    Parse MHJ from a local CSV (rows = multi-turn red-team attempts).

    Schema: Source, temperature, tactic, question_id, time_spent,
    submission_message, message_0, message_1, ..., message_100 — each
    message_N is a JSON-encoded {"body": "...", "role": "user|assistant|system"}.

    Uses MHJ's real attacker-labeled `tactic` column as the technique_family,
    which gives downstream metrics a far richer slice than authored templates
    alone can provide.
    """
    out: List[dict] = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            messages: List[Dict[str, str]] = []
            for j in range(101):
                raw = (row.get(f"message_{j}") or "").strip()
                if not raw:
                    break
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                role = msg.get("role")
                if role in ("user", "assistant"):
                    body = str(msg.get("body") or "").strip()
                    if body:
                        messages.append({"role": role, "content": body})
            if not messages:
                continue
            prompt = next(
                (m["content"] for m in reversed(messages) if m["role"] == "user"),
                messages[-1]["content"],
            )
            tactic = (row.get("tactic") or "").strip()
            tech_family = tactic.lower().replace(" ", "_") if tactic else "unknown"
            qid = row.get("question_id") or str(i)
            out.append({
                "id": f"mhj-{qid}-{i}",
                "source": "mhj",
                "category": "multi_turn_human_jailbreak",
                "label": "harmful",
                "prompt": prompt,
                "messages": messages,
                "_original_index": i,
                "technique_family": tech_family,
            })
    return out


def _load_local_agentharm_chat(json_path: Path) -> List[dict]:
    """
    Parse AgentHarm's `chat` config (single-turn harmful prompts) from local
    JSON. The `harmful` and `harmless_benign` configs are agentic (carry
    target_functions for tool calls); they're skipped here since this
    harness is chat-only — use the chat config which AISI extracted for
    chat-mode evaluation.
    """
    with open(json_path) as f:
        data = json.load(f)
    out: List[dict] = []
    for i, b in enumerate(data.get("behaviors", [])):
        prompt = b.get("prompt")
        if not prompt:
            continue
        out.append({
            "id": f"agentharm-chat-{b.get('id', i)}",
            "source": "agentharm",
            "category": str(b.get("category", "agentharm")).lower(),
            "label": "harmful",
            "prompt": str(prompt),
            "messages": None,
            "_original_index": i,
        })
    return out


def _parse_hf_source(name: str, ds, cfg: dict) -> List[dict]:
    """
    Parse an HF dataset into the same record shape we use elsewhere.

    Handles three known schemas:
      - Crescendo (tom-gibbs):  "Multi-turn Conversation" column with role-tagged turns
      - MHJ (Scale AI):         "turns" or "messages" columns
      - AgentHarm (AISI):       "prompt" + "category" columns
      - generic fallback:       try prompt/goal/behavior

    Returns records with `messages` populated for multi-turn cases, `prompt` only
    for single-turn cases.
    """
    out: List[dict] = []
    for i, row in enumerate(ds):
        messages = None
        prompt = None

        # ---- Crescendo schema (tom-gibbs/multi-turn_jailbreak_attack_datasets) ----
        # Column name was "Multi-turn Conversation" (capital C) in earlier
        # dataset revisions but is now "Multi-turn conversation" (lowercase
        # c). Field is a Python-repr string of [{"role": ..., "content": ...}, ...]
        # where assistant turns may be "None" (string) for input-only datasets.
        crescendo_conv = (
            row.get("Multi-turn conversation")
            or row.get("Multi-turn Conversation")
            or row.get("multi_turn_conversation")
        )
        if crescendo_conv is not None:
            messages = _normalize_conv(crescendo_conv)
            # For input-only Crescendo, all assistant slots are "None"; strip them
            # so the case represents the USER side of the planned attack.
            messages = [m for m in messages if not (m["role"] == "assistant" and m["content"].lower() == "none")]
            if messages:
                prompt = next(
                    (m["content"] for m in reversed(messages) if m["role"] == "user"),
                    messages[-1]["content"],
                )

        # ---- MHJ schema ----
        elif "turns" in row and isinstance(row["turns"], list):
            messages = _normalize_conv(row["turns"])
            if messages:
                prompt = next(
                    (m["content"] for m in reversed(messages) if m["role"] == "user"),
                    messages[-1]["content"],
                )
        elif "messages" in row and isinstance(row["messages"], list):
            messages = _normalize_conv(row["messages"])
            if messages:
                prompt = next(
                    (m["content"] for m in reversed(messages) if m["role"] == "user"),
                    messages[-1]["content"],
                )

        # ---- Single-turn schemas (text-column datasets, AgentHarm, etc.) ----
        elif "text" in row and row.get("text"):
            # deepset/prompt-injections and Lakera/gandalf_ignore_instructions
            # both use a single `text` column.
            prompt = str(row["text"])
        elif "prompt" in row and row.get("prompt"):
            prompt = str(row["prompt"])
        elif "goal" in row and row.get("goal"):
            prompt = str(row["goal"])
        elif "behavior" in row and row.get("behavior"):
            prompt = str(row["behavior"])

        if not prompt:
            continue

        category = (
            row.get("category")
            or row.get("hazard")
            or row.get("harm_category")
            or cfg.get("default_category", "unknown")
        )
        rec_id = row.get("id") or row.get("Goal ID") or row.get("behavior_id") or f"{name}-{i}"

        # Per-source label/technique_family resolution. Some HF sources need to
        # split per-row by an integer label (deepset_pi: 0=benign / 1=injection)
        # rather than using a single cfg["label"] for every row.
        cfg_label = cfg["label"]
        if cfg_label == "split_by_deepset_label":
            row_label = row.get("label")
            label = "harmful" if int(row_label) == 1 else "benign"
        else:
            label = cfg_label

        # Lakera Gandalf is all "extract the hidden password" attempts;
        # the dataset doesn't sub-categorize so we tag the whole source.
        technique_family = None
        if name == "lakera_gandalf":
            technique_family = "system_prompt_exfiltration"
        elif name.startswith("deepset_pi") and label == "harmful":
            technique_family = "instruction_override"

        out.append({
            "id": f"{name}-{rec_id}",
            "source": name,
            "category": str(category).lower(),
            "label": label,
            "prompt": prompt,
            "messages": messages,
            "_original_index": i,
            "technique_family": technique_family,
        })
    return out


def _normalize_conv(raw) -> List[Dict[str, str]]:
    """Coerce assorted multi-turn formats into OpenAI-style messages."""
    if raw is None:
        return []
    if isinstance(raw, str):
        # Crescendo and some HF datasets serialize the conversation as a
        # Python repr (single-quoted dicts), which json.loads can't parse.
        # Try JSON first, then ast.literal_eval as a fallback before giving
        # up and treating the whole string as a single user turn.
        try:
            raw = json.loads(raw)
        except Exception:
            try:
                raw = ast.literal_eval(raw)
            except Exception:
                return [{"role": "user", "content": raw}]
    if not isinstance(raw, list):
        return []

    out: List[Dict[str, str]] = []
    for turn in raw:
        if isinstance(turn, dict):
            role = turn.get("role") or turn.get("from") or turn.get("speaker") or "user"
            if role in ("human", "user"):
                role = "user"
            elif role in ("gpt", "assistant", "bot", "ai"):
                role = "assistant"
            content = turn.get("content") or turn.get("value") or turn.get("text") or ""
            content = str(content).strip()
            if content:
                out.append({"role": role, "content": content})
        elif isinstance(turn, str):
            s = turn.strip()
            if s:
                out.append({"role": "user", "content": s})
    return out


# Back-compat alias - older callers still reference this name.
_parse_gated_hf = _parse_hf_source


def _generate_multi_turn(
    ranked: Dict[str, List[dict]],
    quota_total: int,
    sources: List[str],
    label: str,
    template_names: List[str],
    wrap_fn,
    name: str,
) -> List[dict]:
    """
    Pull top-ranked prompts from `sources`, wrap each in a multi-turn template,
    and return records ready for tier assignment.

    Cycles through templates round-robin so each case uses a different
    structural pattern. The original prompt becomes the final user turn.
    """
    picks: List[dict] = []
    # Round-robin across sources to keep category diversity
    per_source_iters = []
    for s in sources:
        per_source_iters.append(iter(ranked.get(s, [])))

    seen_ids = set()
    while len(picks) < quota_total * 2:  # over-pick a bit so dedup doesn't starve
        progressed = False
        for it in per_source_iters:
            try:
                rec = next(it)
            except StopIteration:
                continue
            if rec["id"] in seen_ids:
                continue
            seen_ids.add(rec["id"])
            picks.append(rec)
            progressed = True
            if len(picks) >= quota_total * 2:
                break
        if not progressed:
            break

    # Trim to quota
    picks = picks[:quota_total]

    out: List[dict] = []
    for i, rec in enumerate(picks):
        template = template_names[i % len(template_names)]
        try:
            messages = wrap_fn(template, rec["prompt"])
        except Exception as e:
            print(f"  [WARN] template {template} failed on {rec['id']}: {e}", file=sys.stderr)
            continue
        out.append({
            "id": f"{name}-{template}-{i:03d}",
            "source": name,
            "category": f"multi_turn_{template}",
            "label": label,
            "prompt": rec["prompt"],  # final user turn for quick reference
            "messages": messages,
            "quality_score": 0.95,  # authored, high signal
            "rank_in_source": i + 1,
            "_original_index": i,
            "technique_family": technique_family_for(template, label),
        })
    return out



def main():
    p = argparse.ArgumentParser(description="Build the static guardrail eval corpus.")
    p.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent.parent / "data" / "corpus_v1.json"),
        help="Output JSON path.",
    )
    p.add_argument("--seed", type=int, default=42, help="Reserved for future random tiebreaks.")
    p.add_argument(
        "--local-data-dir",
        default=None,
        help="Optional directory holding LOCAL downloads of gated HuggingFace "
             "datasets (MHJ CSV + AgentHarm chat JSON). When set, the builder "
             "loads these from disk INSTEAD of hitting the HF API for those "
             "sources, so users who manually downloaded the gated data after "
             "accepting access agreements don't need HF_TOKEN at build time. "
             "Looks for: harmbench_behaviors.csv (MHJ, despite the filename) "
             "and chat_public_test.json (AgentHarm chat).",
    )
    args = p.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    corpus = build_corpus(seed=args.seed, local_data_dir=args.local_data_dir)
    with open(out_path, "w") as f:
        json.dump(corpus, f, indent=2)

    size_kb = out_path.stat().st_size / 1024
    print(f"\nWrote {len(corpus['cases'])} cases to {out_path} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
