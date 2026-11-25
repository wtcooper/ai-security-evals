"""The Inspect Petri task behind the multi-turn checks (mt_misuse, mt_legitimate).

Needs inspect_ai and inspect-petri==3.1.1 in the Inspect venv; inspect_petri is imported when
the task is built, so the rest of the suite works without it. Specs, seeds and the rubric
come from mt_checks.py.

Model roles. The shared runner passes the model under test as the eval's model, binds
`target` to the same model (the checks' `arm_roles`) and `judge` to the judge; this task binds
`auditor` (the simulated user, from --auditor). run_suite.py refuses an auditor that is a
model under test, and the first solver checks it again inside the run.
"""
from __future__ import annotations

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import get_model, model_roles
from inspect_ai.solver import Generate, Solver, TaskState, solver

import mt_checks

PETRI_VERSION = "3.1.1"


def _petri():
    try:
        import inspect_petri
    except ImportError as exc:
        raise RuntimeError(
            "the multi-turn checks need inspect-petri: install it into the Inspect venv with "
            f"`uv pip install --python .venv-inspect/bin/python inspect-petri=={PETRI_VERSION}` "
            "(it adds packages and leaves inspect_ai as it is)") from exc
    return inspect_petri


@solver
def auditor_is_not_under_test() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        roles = dict(model_roles())
        auditor = roles.get("auditor")
        if auditor is not None and str(auditor) == str(get_model()):
            raise ValueError("the auditor is the model under test; pass a different --auditor")
        if "target" not in roles:
            raise ValueError("no `target` role: run the multi-turn checks through run_suite.py, "
                             "which binds it to the model under test")
        return state

    return solve


@task
def multiturn_task(kind: str = "misuse", design: str = "standard",
                   auditor: str | None = None) -> Task:
    """One conversation per seed: the auditor plays the user, the target is the model under
    test, and the judge grades the whole conversation on the lane's yes/no dimensions."""
    petri = _petri()
    samples = [Sample(id=s["id"], input=s["input"], metadata=s["metadata"])
               for s in mt_checks.seeds(kind, design)]
    tools = petri.auditor_tools(prefill=False, rollback=False, target_tools="none",
                                exclude={"set_system_message"})
    user = petri.auditor_agent(max_turns=mt_checks.AUDITOR_TURNS, compaction=False,
                               tools=tools, system_message=mt_checks.AUDITOR_SYSTEM_MESSAGE)
    dimensions = str(mt_checks.DIM_DIR)
    return Task(
        dataset=MemoryDataset(samples, name=f"mt_{kind}_{design}"),
        solver=[auditor_is_not_under_test(),
                petri.audit_solver(auditor=user, target=petri.target_agent(system_required=False))],
        scorer=petri.audit_judge(dimensions, instructions=mt_checks.JUDGE_INSTRUCTIONS),
        viewer=petri.audit_viewer(dimensions),
        model_roles={"auditor": auditor} if auditor else None,
        metadata={"rubric_version": mt_checks.RUBRIC_VERSION, "design": design},
        name=f"mt_{kind}",
    )
