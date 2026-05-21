"""
guardrail_eval: A static test harness for LLM guardrails via any gateway.

All outcome classification goes through an LLM-as-judge - there is no
keyword-based classifier. The judge produces one of four label-blind outcomes:
REFUSAL, CONTROL_BLOCK, COMPLIANCE, ERROR. Metrics map (outcome, label) to
TP/FP/FN/TN, with ERROR excluded from F1/Recall/FPR denominators.
"""

from .corpus import (
    TestCase,
    # Static corpus (preferred)
    load_static_corpus,
    load_static_suite,
    describe_static_corpus,
    DEFAULT_CORPUS_PATH,
    TIER_SIZES,
    # Dynamic loaders
    load_harmbench,
    load_xstest,
    load_strongreject,
    load_ailuminate_demo,
    load_advbench,
    load_mhj,
    load_multiturn_crescendo,
    load_agentharm,
    load_alpaca_benign,
    # Convenience
    load_all,
    load_standard_suite,
    validate_benign_present,
    DATASET_LOADERS,
)
from .providers import (
    Provider, ProviderResponse,
    LiteLLMProvider, OpenAICompatibleProvider, RESTProvider,
    make_provider, PROVIDERS,
)
from .judge import (
    Judge, JudgeOutcome, LLMJudge,
    REFUSAL, CONTROL_BLOCK, COMPLIANCE, ERROR, OUTCOMES,
)
from .runner import (
    GuardrailTester, TestResult,
    DEFAULT_MOCK_RESPONSE, DEFAULT_BENIGN_PROMPT,
)
from .metrics import (
    compute_metrics,
    compute_metrics_by_category,
    compute_metrics_by_source,
    compute_metrics_by_technique_family,
    compute_outcome_distribution,
    compute_replicate_stability,
    latency_stats,
    print_report,
)

__version__ = "0.5.0"
