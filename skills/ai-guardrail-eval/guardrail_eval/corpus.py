"""
Corpus loaders for standardized guardrail evaluation datasets.

All loaders return List[TestCase] with a unified schema, drawing from public
benchmarks. No homegrown prompts - everything is traceable to a published
benchmark so results are comparable and defensible.

Datasets (as of May 2026):
    harmbench       - HarmBench standard behaviors (Mazeika et al. 2024). Still
                      the most-cited harmful behavior benchmark.   [harmful]
    xstest          - 250 safe-but-tricky + 200 unsafe contrasts (Roettger 2024).
                      THE canonical false-positive benchmark.      [mixed]
    strongreject    - 313 harmful prompts across 6 categories (Souly 2024).
                      Widely used as an ASR scoring corpus.        [harmful]
    ailuminate_demo - MLCommons AILuminate v1.0/v1.1 DEMO (Ghosh 2025). 1,200
                      prompts across 12 hazard categories, CC-BY-4.0. Industry
                      standard as of 2026.                         [harmful]
    advbench        - Zou et al. harmful behaviors (the classic).  [harmful]
    mhj             - Multi-Turn Human Jailbreaks (Li/Scale 2024). 537 multi-turn
                      conversations from professional red teamers. State of the
                      art for multi-turn; gated, needs HF_TOKEN.   [harmful, multi-turn]
    crescendo       - Older multi-turn fallback (tom-gibbs).       [harmful, multi-turn]
    agentharm       - 110 malicious agent tasks (AISI 2024, gated). [harmful]
    alpaca_benign   - Clean benign baseline.                       [benign]

For a quick balanced ~100-case evaluation suite ready for replicate runs, use
`load_standard_suite()`. It stratifies across adversarial, harmful, multi-turn,
and benign so F1 is always computable.
"""

import csv
import json
import random
import urllib.request
from io import StringIO
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Callable


@dataclass
class TestCase:
    """Unified test case format across all datasets."""
    id: str
    source: str                                          # which dataset
    category: str                                        # harm category or "benign"
    label: str                                           # "harmful" or "benign"
    prompt: str                                          # single-turn input
    messages: Optional[List[Dict[str, str]]] = None      # multi-turn conversation
    expected_output: Optional[str] = None                # for output-side testing
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _safe_load(name: str, **kwargs):
    """Load a HuggingFace dataset, returning None on failure with a clear message."""
    try:
        from datasets import load_dataset
        return load_dataset(name, **kwargs)
    except Exception as e:
        print(f"  [WARN] Could not load {name}: {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------------
# HarmBench - standardized harmful-behavior benchmark
# Paper: Mazeika et al., HarmBench (2024)
# ---------------------------------------------------------------------------

def load_harmbench(limit: Optional[int] = None) -> List[TestCase]:
    """HarmBench standard behaviors - all harmful prompts."""
    ds = _safe_load("walledai/HarmBench", "standard", split="train")
    if ds is None:
        return []

    cases: List[TestCase] = []
    for i, row in enumerate(ds):
        if limit and i >= limit:
            break
        prompt = row.get("prompt") or row.get("behavior") or ""
        if not prompt:
            continue
        cases.append(TestCase(
            id=f"harmbench-{i}",
            source="harmbench",
            category=str(row.get("category", "unknown")),
            label="harmful",
            prompt=prompt,
            metadata={"semantic_category": row.get("semantic_category")},
        ))
    return cases


# ---------------------------------------------------------------------------
# XSTest - exaggerated safety / false-refusal benchmark
# Paper: Röttger et al., XSTest (2024)
# This is the only widely-used dataset specifically designed to measure FPR.
# ---------------------------------------------------------------------------

def load_xstest(limit: Optional[int] = None) -> List[TestCase]:
    """
    XSTest mixes 250 safe prompts (that LOOK unsafe) with 200 unsafe contrasts.
    Safe prompts -> label='benign' -> a block here is a False Positive.
    Unsafe prompts -> label='harmful' -> a block is a True Positive.
    """
    # gpt4 subset contains the canonical 450 prompts
    ds = _safe_load("natolambert/xstest-v2-copy", split="gpt4")
    if ds is None:
        return []

    cases: List[TestCase] = []
    for i, row in enumerate(ds):
        if limit and i >= limit:
            break
        prompt_type = str(row.get("type", ""))
        is_safe = prompt_type.startswith("safe_")
        prompt = row.get("prompt") or ""
        if not prompt:
            continue
        cases.append(TestCase(
            id=f"xstest-{row.get('id', i)}",
            source="xstest",
            category=prompt_type,
            label="benign" if is_safe else "harmful",
            prompt=prompt,
        ))
    return cases


# ---------------------------------------------------------------------------
# AILuminate DEMO v1.0 - MLCommons industry-standard safety benchmark
# Paper: Ghosh et al., AILuminate v1.0 (2025), arXiv 2503.05731
# 1,200 prompts across 12 hazard categories, CC-BY-4.0, English en_US.
# Hosted as CSV on the official mlcommons/ailuminate GitHub repo.
# ---------------------------------------------------------------------------

AILUMINATE_DEMO_URL = (
    "https://raw.githubusercontent.com/mlcommons/ailuminate/main/"
    "airr_official_1.0_demo_en_us_prompt_set_release.csv"
)

# Hazard code -> human-readable category (from the AILuminate v1.0 spec)
AILUMINATE_HAZARDS = {
    "vcr": "violent_crimes",
    "src": "sex_related_crimes",
    "cse": "child_sexual_exploitation",
    "ssh": "suicide_self_harm",
    "iwp": "indiscriminate_weapons",
    "ipv": "ip_violations",
    "dfm": "defamation",
    "ncr": "non_violent_crimes",
    "hte": "hate",
    "prv": "privacy",
    "spc_ele": "specialized_advice_elections",
    "spc_fin": "specialized_advice_financial",
    "spc_hlt": "specialized_advice_health",
    "sxc_prn": "sexual_content_pornographic",
    "spc": "specialized_advice",
    "sxc": "sexual_content",
}


def load_ailuminate_demo(limit=None):
    """AILuminate v1.0 DEMO - 1,200 prompts across 12 hazard categories."""
    try:
        with urllib.request.urlopen(AILUMINATE_DEMO_URL, timeout=20) as resp:
            text = resp.read().decode("utf-8")
    except Exception as e:
        print(f"  [WARN] Could not fetch AILuminate DEMO: {e}")
        return []

    reader = csv.DictReader(StringIO(text))
    cases = []
    for i, row in enumerate(reader):
        if limit and i >= limit:
            break
        prompt = (
            row.get("Prompt_text")
            or row.get("prompt_text")
            or row.get("Prompt")
            or ""
        ).strip()
        if not prompt:
            continue
        hazard_code = (row.get("Hazard") or row.get("hazard") or "").strip().lower()
        category = AILUMINATE_HAZARDS.get(hazard_code, hazard_code or "unknown")
        persona = row.get("Persona") or row.get("persona") or "normal"
        prompt_id = (
            row.get("Release_prompt_id")
            or row.get("release_prompt_id")
            or row.get("Prompt_hash")
            or f"ail-{i}"
        )
        cases.append(TestCase(
            id=f"ailuminate-{prompt_id}",
            source="ailuminate_demo",
            category=category,
            label="harmful",  # all DEMO prompts attempt to elicit harm
            prompt=prompt,
            metadata={"hazard_code": hazard_code, "persona": persona},
        ))
    return cases


# ---------------------------------------------------------------------------
# StrongREJECT - 313 prompts across 6 harm categories
# Paper: Souly et al., StrongREJECT (2024)
# ---------------------------------------------------------------------------

def load_strongreject(limit: Optional[int] = None) -> List[TestCase]:
    """StrongREJECT - harmful prompts across 6 categories."""
    # Try a few known mirror locations
    ds = (
        _safe_load("walledai/StrongREJECT", split="train")
        or _safe_load("csHugging/StrongReject", split="train")
    )

    # Last resort: pull the canonical CSV directly from the official GitHub.
    if ds is None:
        try:
            import csv
            from io import StringIO
            import urllib.request
            url = "https://raw.githubusercontent.com/alexandrasouly/strongreject/main/strongreject_dataset/strongreject_dataset.csv"
            with urllib.request.urlopen(url, timeout=15) as resp:
                text = resp.read().decode("utf-8")
            reader = csv.DictReader(StringIO(text))
            ds = list(reader)
        except Exception as e:
            print(f"  [WARN] StrongREJECT CSV fallback failed: {e}")
            return []

    cases: List[TestCase] = []
    iterable = ds if isinstance(ds, list) else ds
    for i, row in enumerate(iterable):
        if limit and i >= limit:
            break
        prompt = (
            row.get("prompt")
            or row.get("forbidden_prompt")
            or row.get("question")
            or ""
        )
        if not prompt:
            continue
        cases.append(TestCase(
            id=f"strongreject-{i}",
            source="strongreject",
            category=str(row.get("category", "unknown")),
            label="harmful",
            prompt=prompt,
        ))
    return cases


# ---------------------------------------------------------------------------
# AdvBench - Zou et al. harmful behaviors (the classic 520-prompt set)
# ---------------------------------------------------------------------------

def load_advbench(limit: Optional[int] = None) -> List[TestCase]:
    """AdvBench - Zou et al. harmful behaviors."""
    ds = (
        _safe_load("walledai/AdvBench", split="train")
        or _safe_load("argilla/advbench-validation", split="train")
    )
    if ds is None:
        return []

    cases: List[TestCase] = []
    for i, row in enumerate(ds):
        if limit and i >= limit:
            break
        prompt = row.get("prompt") or row.get("goal") or ""
        if not prompt:
            continue
        cases.append(TestCase(
            id=f"advbench-{i}",
            source="advbench",
            category="harmful_behavior",
            label="harmful",
            prompt=prompt,
        ))
    return cases


# ---------------------------------------------------------------------------
# MHJ - Multi-Turn Human Jailbreaks (Scale AI, 2024)
# Paper: Li et al., "LLM Defenses Are Not Robust to Multi-Turn Human Jailbreaks"
# HF: ScaleAI/mhj - 2,912 prompts across 537 multi-turn jailbreak conversations
# from professional commercial red teamers. Gated, requires HF_TOKEN with access.
# This is the state-of-the-art static multi-turn benchmark as of 2026.
# ---------------------------------------------------------------------------

def load_mhj(limit=None):
    """
    MHJ multi-turn jailbreaks - 537 professionally-redteamed conversations.

    Gated on HuggingFace - request access at https://huggingface.co/datasets/ScaleAI/mhj
    and set HF_TOKEN. Returns one TestCase per conversation, with the full
    turn history in .messages for static replay.
    """
    ds = _safe_load("ScaleAI/mhj", split="train")
    if ds is None:
        print("  [INFO] MHJ load failed - falling back to crescendo (tom-gibbs)")
        return load_multiturn_crescendo(limit=limit)

    cases = []
    by_conv = {}

    # MHJ schema varies slightly across mirrors; collect rows per conversation.
    for i, row in enumerate(ds):
        conv_id = (
            row.get("conversation_id")
            or row.get("conv_id")
            or row.get("source_id")
            or row.get("behavior_id")
            or f"conv-{i}"
        )

        # If the row IS the conversation (list of turns), use directly.
        if "turns" in row or "messages" in row or "conversation" in row:
            raw = row.get("turns") or row.get("messages") or row.get("conversation")
            messages = _normalize_conversation(raw)
            if not messages:
                continue
            cases.append(TestCase(
                id=f"mhj-{conv_id}",
                source="mhj",
                category=str(row.get("tactic") or row.get("category") or "multiturn"),
                label="harmful",
                prompt=messages[-1].get("content", ""),
                messages=messages,
                metadata={
                    "tactic": row.get("tactic"),
                    "harmbench_behavior": row.get("behavior") or row.get("harmbench_behavior"),
                },
            ))
        else:
            # Each row is a single turn - group by conversation id.
            content = row.get("turn") or row.get("text") or row.get("content") or ""
            role = row.get("role") or "user"
            entry = by_conv.setdefault(conv_id, {
                "messages": [],
                "tactic": row.get("tactic"),
                "behavior": row.get("behavior") or row.get("harmbench_behavior"),
            })
            if content:
                entry["messages"].append({"role": role, "content": content})

    # Materialize any grouped conversations
    for conv_id, payload in by_conv.items():
        msgs = payload["messages"]
        if not msgs:
            continue
        cases.append(TestCase(
            id=f"mhj-{conv_id}",
            source="mhj",
            category=str(payload.get("tactic") or "multiturn"),
            label="harmful",
            prompt=msgs[-1].get("content", ""),
            messages=msgs,
            metadata={"tactic": payload.get("tactic"), "harmbench_behavior": payload.get("behavior")},
        ))

    if limit:
        cases = cases[:limit]
    return cases


# ---------------------------------------------------------------------------
# Crescendo (tom-gibbs) - older multi-turn fallback when MHJ is unavailable
# Paper: Russinovich et al., Crescendo (2024)
# ---------------------------------------------------------------------------

def load_multiturn_crescendo(limit: Optional[int] = None) -> List[TestCase]:
    """
    Multi-turn jailbreak conversations. Each row contains a conversation history
    designed to gradually escalate toward a harmful objective (Crescendo-style).
    Sent as a `messages` list to test guardrail context awareness.
    """
    # The dataset has multiple configs; 'harmful' contains the multi-turn attacks.
    ds = _safe_load(
        "tom-gibbs/multi-turn_jailbreak_attack_datasets",
        "harmful",
        split="train",
    )
    if ds is None:
        # Fallback: try without config
        ds = _safe_load("tom-gibbs/multi-turn_jailbreak_attack_datasets", split="train")
    if ds is None:
        return []

    cases: List[TestCase] = []
    for i, row in enumerate(ds):
        if limit and i >= limit:
            break

        # The conversation field may be named differently across mirrors
        conv_raw = (
            row.get("Multi-turn Conversation")
            or row.get("multi_turn_conversation")
            or row.get("multi-turn_conversation")
            or row.get("conversation")
            or row.get("messages")
        )

        messages = _normalize_conversation(conv_raw)
        if not messages:
            continue

        prompt = row.get("Prompt") or row.get("prompt") or messages[-1].get("content", "")

        cases.append(TestCase(
            id=f"crescendo-{i}",
            source="crescendo",
            category="multiturn_jailbreak",
            label="harmful",
            prompt=prompt,
            messages=messages,
            metadata={
                "input_cipher": row.get("Input-cipher"),
                "output_cipher": row.get("Output-cipher"),
            },
        ))
    return cases


def _normalize_conversation(raw) -> List[Dict[str, str]]:
    """Coerce assorted conversation formats into OpenAI-style messages."""
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return [{"role": "user", "content": raw}]
    if not isinstance(raw, list):
        return []

    out: List[Dict[str, str]] = []
    for turn in raw:
        if isinstance(turn, dict):
            role = turn.get("role") or turn.get("from") or "user"
            # Normalize 'human'/'gpt'/'assistant' role names
            if role in ("human", "user"):
                role = "user"
            elif role in ("gpt", "assistant", "bot"):
                role = "assistant"
            content = turn.get("content") or turn.get("value") or ""
            if content and content.lower() != "none":
                out.append({"role": role, "content": content})
        elif isinstance(turn, str):
            out.append({"role": "user", "content": turn})
    return out


# ---------------------------------------------------------------------------
# AgentHarm - malicious agent task benchmark
# Paper: Andriushchenko et al., AgentHarm (2024)
# Note: dataset is gated on HF. Requires HF_TOKEN with access.
# ---------------------------------------------------------------------------

def load_agentharm(limit: Optional[int] = None) -> List[TestCase]:
    """AgentHarm - 110 malicious agent tasks across 11 categories. Gated dataset."""
    ds = _safe_load("ai-safety-institute/AgentHarm", "harmful", split="test_public")
    if ds is None:
        return []

    cases: List[TestCase] = []
    for i, row in enumerate(ds):
        if limit and i >= limit:
            break
        prompt = row.get("prompt") or ""
        if not prompt:
            continue
        cases.append(TestCase(
            id=f"agentharm-{row.get('id', i)}",
            source="agentharm",
            category=str(row.get("category", "unknown")),
            label="harmful",
            prompt=prompt,
            metadata={
                "name": row.get("name"),
                "target_functions": row.get("target_functions"),
            },
        ))
    return cases


# ---------------------------------------------------------------------------
# Alpaca - clean benign baseline (for measuring FPR on normal traffic)
# ---------------------------------------------------------------------------

def load_alpaca_benign(limit: int = 200) -> List[TestCase]:
    """Alpaca instructions - clean benign baseline. Default 200-row sample."""
    ds = _safe_load("tatsu-lab/alpaca", split="train")
    if ds is None:
        return []

    cases: List[TestCase] = []
    for i, row in enumerate(ds):
        if i >= limit:
            break
        instr = row.get("instruction") or ""
        inp = row.get("input") or ""
        prompt = f"{instr}\n\n{inp}".strip() if inp else instr
        if not prompt:
            continue
        cases.append(TestCase(
            id=f"alpaca-{i}",
            source="alpaca_benign",
            category="benign",
            label="benign",
            prompt=prompt,
        ))
    return cases


# ---------------------------------------------------------------------------
# Static corpus loaders (PREFERRED over dynamic sampling)
# ---------------------------------------------------------------------------
#
# The static corpus is built ONCE by scripts/build_corpus.py and committed to
# the repo as data/corpus_v1.json. This guarantees every team / CI run uses
# the IDENTICAL set of cases, so results are comparable across guardrails,
# replicates, and time. Quality ranking + tiering happens at build time.
#
# Use these in production. The dynamic loaders below are kept for ad-hoc
# experimentation and as a fallback if the static file is unavailable.

from pathlib import Path

DEFAULT_CORPUS_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "corpus_v1.json"
)

# Tier -> cumulative size mapping (smoke ⊂ standard ⊂ comprehensive)
TIER_SIZES = {
    "smoke": 1,          # only tier 1
    "standard": 2,       # tiers 1+2
    "comprehensive": 3,  # tiers 1+2+3
}


def load_static_corpus(path=None):
    """
    Load the full static corpus JSON. Returns the raw dict (has 'cases',
    'sources', 'composition', 'label_balance', etc.). For a flat list of
    TestCase objects, use load_static_suite() instead.
    """
    p = Path(path) if path else DEFAULT_CORPUS_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"Static corpus not found at {p}. "
            f"Run `python scripts/build_corpus.py` to generate it."
        )
    with open(p, "r") as f:
        return json.load(f)


def load_static_suite(tier="smoke", path=None):
    """
    Load the static suite at the requested quality tier as a List[TestCase].

    tier:
        "smoke"         - 100 cases (highest-quality only)
        "standard"      - 300 cases (smoke + next tier)
        "comprehensive" - 600 cases (all tiers)

    Identical results every run - no sampling at load time. Quality ranking
    and tier assignment happened once at corpus build time.
    """
    if tier not in TIER_SIZES:
        raise ValueError(
            f"Unknown tier {tier!r}. Use one of: {list(TIER_SIZES.keys())}"
        )
    max_tier = TIER_SIZES[tier]
    corpus = load_static_corpus(path)

    cases = []
    for c in corpus["cases"]:
        if c.get("quality_tier", 99) <= max_tier:
            cases.append(TestCase(
                id=c["id"],
                source=c["source"],
                category=c["category"],
                label=c["label"],
                prompt=c["prompt"],
                messages=c.get("messages"),
                metadata={
                    "quality_tier": c.get("quality_tier"),
                    "quality_score": c.get("quality_score"),
                    "rank_in_source": c.get("rank_in_source"),
                    "source_url": c.get("source_url"),
                    "citation": c.get("citation"),
                    "license": c.get("license"),
                },
            ))
    return cases


def describe_static_corpus(path=None):
    """Print a one-page summary of the static corpus."""
    c = load_static_corpus(path)
    print(f"Static corpus v{c.get('version')} generated {c.get('generated_at')}")
    print(f"Total cases: {len(c['cases'])}")
    print("\nTier sizes (cumulative):")
    for tier_name in TIER_SIZES:
        max_t = TIER_SIZES[tier_name]
        n = sum(1 for case in c["cases"] if case.get("quality_tier", 99) <= max_t)
        nh = sum(1 for case in c["cases"]
                 if case.get("quality_tier", 99) <= max_t and case["label"] == "harmful")
        nb = sum(1 for case in c["cases"]
                 if case.get("quality_tier", 99) <= max_t and case["label"] == "benign")
        print(f"  {tier_name:<15} {n:>4} cases  (harmful={nh}, benign={nb})")
    print("\nSources:")
    for name, info in c.get("sources", {}).items():
        print(f"  {name:<22} authority={info.get('authority')}  license={info.get('license')}")
    print("\nCitations:")
    for name, info in c.get("sources", {}).items():
        print(f"  {name}: {info.get('citation')}")


# ---------------------------------------------------------------------------
# Registry + convenience loaders (dynamic - kept for flexibility)
# ---------------------------------------------------------------------------

DATASET_LOADERS = {
    "harmbench": load_harmbench,
    "xstest": load_xstest,
    "strongreject": load_strongreject,
    "ailuminate_demo": load_ailuminate_demo,
    "advbench": load_advbench,
    "mhj": load_mhj,
    "crescendo": load_multiturn_crescendo,
    "agentharm": load_agentharm,
    "alpaca_benign": load_alpaca_benign,
}


def load_standard_suite(seed=42, tier="smoke"):
    """
    Backwards-compatible alias for load_static_suite().

    Returns the pre-built, quality-ranked static suite at the requested tier.
    Build/regenerate the static corpus with:
        python scripts/build_corpus.py
    """
    return load_static_suite(tier=tier)


def load_all(datasets, limit_per_dataset=None):
    """Load multiple datasets and concatenate. Skips unknown / failed ones."""
    cases = []
    for name in datasets:
        loader = DATASET_LOADERS.get(name)
        if loader is None:
            print(f"  [WARN] Unknown dataset '{name}', skipping")
            continue
        print(f"Loading {name}...")
        try:
            sub = loader(limit=limit_per_dataset) if limit_per_dataset else loader()
            cases.extend(sub)
            print(f"  -> {len(sub)} cases")
        except TypeError:
            sub = loader()
            cases.extend(sub)
            print(f"  -> {len(sub)} cases")
        except Exception as e:
            print(f"  [WARN] {name} failed: {e}")
    return cases


def validate_benign_present(cases, min_benign=10):
    """
    Hard check: F1 requires both labels. Raise if the corpus lacks benign cases.

    Call this before running a batch when you intend to report F1/FPR.
    """
    benign = sum(1 for c in cases if c.label == "benign")
    harmful = sum(1 for c in cases if c.label == "harmful")
    if benign < min_benign:
        raise ValueError(
            f"Corpus has only {benign} benign cases (need >= {min_benign}). "
            f"F1 and FPR cannot be meaningfully computed without a benign baseline. "
            f"Add 'xstest' or 'alpaca_benign' to your datasets, or use "
            f"load_standard_suite()."
        )
    if harmful == 0:
        raise ValueError("Corpus has no harmful cases; nothing to detect.")
