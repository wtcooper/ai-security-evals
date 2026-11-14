"""The model-bench suite: which Inspect benchmarks run, how they are routed, what is read.

Pure data + arithmetic. Nothing here imports inspect_ai, so the suite can be listed, costed
and unit-tested from any Python (the benchmarks themselves run in `.venv-inspect`).

Every `module` / `function` / `metric_key` below was checked against inspect_evals 0.29.0.
Re-check them when you upgrade: scorer and metric names are not a stable API, and a wrong
`metric_key` reads as "no score", never as a wrong number (see run_suite.extract).

What may be added here: benchmarks that measure whether a model RESISTS attack, running
pure-API or against in-memory mock tools. Benchmarks that elicit offensive capability and
need a Docker sandbox (cve_bench, cybergym, cybench, threecb) answer a different question
and need supervision; they are deliberately not in this suite.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

HIGHER, LOWER = "higher_is_better", "lower_is_better"


@dataclass(frozen=True)
class Check:
    id: str
    dimension: str               # the risk dimension this check is the measurement for
    module: str
    function: str
    metric_key: str              # `<scorer or group>.<metric>` exactly as Inspect emits it
    direction: str
    percent: bool = False        # scorer reports 0-100; divided by 100 on read
    task_kwargs: dict = field(default_factory=dict)
    judge_kwargs: tuple = ()     # task args that must receive the judge model string
    judge_roles: tuple = ()      # Inspect model roles the scorers resolve
    epochs: int | None = None    # override the task's default epochs
    unresolved_key: str | None = None   # scorer-reported count of unusable judge verdicts
    companion_key: str | None = None    # ungated metric that must be read alongside
    calls_per_sample: int = 1
    dataset_size: int | None = None
    note: str = ""

    @property
    def needs_judge(self) -> bool:
        return bool(self.judge_kwargs or self.judge_roles)


_CYSE4 = "inspect_evals.cyberseceval_4"
_ATB = "inspect_evals.agent_threat_bench"
_TOOL_CAVEAT = ("A model too weak to call tools scores perfectly here by failing to act: "
                "read security next to the companion utility metric.")

CHECKS: tuple[Check, ...] = (
    Check("cyse4_mitre", "direct misuse", _CYSE4, "cyse4_mitre",
          "mitre_scorer.accuracy", HIGHER,
          judge_kwargs=("judge_llm", "expansion_llm"), judge_roles=("grader", "expander"),
          unresolved_key="mitre_scorer.else_count", calls_per_sample=3, dataset_size=1000,
          note="Share of MITRE ATT&CK-mapped offensive requests NOT assisted. Subject, "
               "expansion model and judge: the most expensive check per sample."),
    Check("cyse4_mitre_frr", "over-refusal", _CYSE4, "cyse4_mitre_frr",
          "refusal_scorer.refusal_rate", LOWER, dataset_size=750,
          note="Benign security questions wrongly refused. The mandatory pair of "
               "cyse4_mitre: without it a model passes by refusing everything."),
    Check("strong_reject", "harmful-request refusal", "inspect_evals.strong_reject",
          "strong_reject", "strong_reject_scorer.jailbreak_rate", LOWER,
          judge_kwargs=("judge_llm",), judge_roles=("grader",),
          calls_per_sample=2, dataset_size=313,
          note="313 forbidden prompts asked DIRECTLY, no jailbreak applied: the baseline. "
               "Unparseable judge replies are dropped from the denominator, so check n."),
    Check("strong_reject_aim", "jailbreak robustness", "inspect_evals.strong_reject",
          "strong_reject", "strong_reject_scorer.jailbreak_rate", LOWER,
          task_kwargs={"jailbreak_method": "AIM"},
          judge_kwargs=("judge_llm",), judge_roles=("grader",),
          calls_per_sample=2, dataset_size=313,
          note="The same 313 prompts wrapped in the AIM jailbreak. The delta against "
               "strong_reject is the jailbreak uplift. AIM is the only transformation "
               "inspect_evals bundles and it is old; treat a low rate as a floor."),
    Check("cyse4_instruct", "insecure code", _CYSE4, "cyse4_instruct",
          "security_scorer.vulnerable_percentage", LOWER, percent=True, dataset_size=1916,
          note="Share of instructed code outputs with a detected vulnerability "
               "(deterministic semgrep-based detector, no judge)."),
    Check("cyse4_multilingual_prompt_injection", "injection via content", _CYSE4,
          "cyse4_multilingual_prompt_injection", "prompt_injection_scorer.accuracy", HIGHER,
          judge_kwargs=("judge_llm",), judge_roles=("grader",), epochs=1,
          calls_per_sample=2, dataset_size=1004,
          note="Share of injections resisted, across languages. Upstream defaults to 4 "
               "epochs; pinned to 1 here."),
    Check("agentdojo", "injection via tools", "inspect_evals.agentdojo", "agentdojo",
          "security.accuracy", HIGHER, task_kwargs={"with_sandbox_tasks": "no"},
          companion_key="utility.accuracy", calls_per_sample=6, dataset_size=944,
          note="Share of agent episodes where the injected goal did NOT succeed. "
               + _TOOL_CAVEAT),
    Check("atb_memory_poison", "memory poisoning", _ATB, "agent_threat_bench_memory_poison",
          "security.accuracy", HIGHER, companion_key="utility.accuracy",
          calls_per_sample=4, dataset_size=10,
          note="OWASP ASI06. Only 10 cases: one case is 10 points. " + _TOOL_CAVEAT),
    # --- extended: registered, not in the core profile -------------------------------
    Check("cyse4_autocomplete", "insecure code (completion)", _CYSE4, "cyse4_autocomplete",
          "security_scorer.vulnerable_percentage", LOWER, percent=True, dataset_size=1916,
          note="cyse4_instruct's corpus as completion prompts: a second modality, not a "
               "second dimension. Run it if IDE completion is the deployment."),
    Check("atb_autonomy_hijack", "injection via tools (small)", _ATB,
          "agent_threat_bench_autonomy_hijack", "security.accuracy", HIGHER,
          companion_key="utility.accuracy", calls_per_sample=4, dataset_size=6,
          note="Same threat model as agentdojo over 6 cases. " + _TOOL_CAVEAT),
    Check("atb_data_exfil", "data exfiltration via tools (small)", _ATB,
          "agent_threat_bench_data_exfil", "security.accuracy", HIGHER,
          companion_key="utility.accuracy", calls_per_sample=4, dataset_size=8,
          note="Scored on tool-call arguments, 8 cases. " + _TOOL_CAVEAT),
)

BY_ID = {c.id: c for c in CHECKS}

PROFILES: dict[str, tuple[str, ...]] = {
    # One check per risk dimension.
    "core": ("cyse4_mitre", "cyse4_mitre_frr", "strong_reject", "strong_reject_aim",
             "cyse4_instruct", "cyse4_multilingual_prompt_injection", "agentdojo",
             "atb_memory_poison"),
    # No judge model needed at all: the cheapest meaningful run.
    "nojudge": ("cyse4_mitre_frr", "cyse4_instruct", "agentdojo", "atb_memory_poison"),
    "all": tuple(c.id for c in CHECKS),
}

# Samples per check. Near a 0.9 rate the 95% interval is about +/-12 points at n=25 and
# +/-6 at n=100, so "quick" proves the wiring and nothing else.
DEPTHS: dict[str, int | None] = {"quick": 25, "good": 100, "full": None}


def resolve_checks(spec: str) -> list[Check]:
    """A profile name, or a comma-separated list of check ids."""
    ids = PROFILES.get(spec) or tuple(s.strip() for s in spec.split(",") if s.strip())
    unknown = [i for i in ids if i not in BY_ID]
    if unknown or not ids:
        raise ValueError(f"unknown check(s) {unknown}; known: {sorted(BY_ID)}; "
                         f"profiles: {sorted(PROFILES)}")
    return [BY_ID[i] for i in ids]


def resolve_depth(spec: str) -> int | None:
    if spec in DEPTHS:
        return DEPTHS[spec]
    n = int(spec)
    if n < 1:
        raise ValueError("depth must be quick, good, full or a positive integer")
    return n


def samples_for(check: Check, depth: int | None) -> int | None:
    """Sample count for a check at a depth; None means the whole dataset, size unknown."""
    if depth is None:
        return check.dataset_size
    return min(depth, check.dataset_size) if check.dataset_size else depth


def plan(checks: list[Check], depth: int | None) -> dict:
    """Tests and model calls a run will make, so the cost is visible before it starts."""
    rows = []
    for c in checks:
        n = samples_for(c, depth) or 0
        rows.append({"check": c.id, "samples": n, "calls": n * c.calls_per_sample,
                     "judge": c.needs_judge})
    return {"rows": rows, "samples": sum(r["samples"] for r in rows),
            "calls": sum(r["calls"] for r in rows)}


def wilson_ci(rate: float, n: int, z: float = 1.959964) -> tuple[float, float]:
    """95% Wilson interval for a proportion observed over n samples."""
    if n <= 0:
        return (0.0, 1.0)
    denom = 1 + z * z / n
    centre = (rate + z * z / (2 * n)) / denom
    half = z * math.sqrt(rate * (1 - rate) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def normalize(rate: float, direction: str) -> float:
    """0-100 with 100 always the good end. Display and ordering only."""
    r = min(max(rate, 0.0), 1.0)
    return round((1 - r if direction == LOWER else r) * 100, 1)
