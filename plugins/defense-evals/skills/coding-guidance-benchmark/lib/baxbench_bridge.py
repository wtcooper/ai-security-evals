#!/usr/bin/env python3
"""Run with BaxBench's own interpreter (Python 3.12 with its Pipfile installed), from the
clone's root. Writes, for each requested task, the agent prompt BaxBench builds and the
Dockerfile of its framework. Importing BaxBench's `env` package connects to the Docker
daemon (env/base.py calls docker.from_env() at import), so the daemon must be up.

    pipenv run python <skill>/lib/baxbench_bridge.py --src src --tasks '["Calculator@Python-Flask"]' --out bridge.json
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--src", required=True, help="the clone's src directory")
    p.add_argument("--tasks", required=True, help="JSON list of <scenario>@<framework> ids")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)

    sys.path.insert(0, args.src)
    from env import all_envs                       # noqa: E402  (BaxBench)
    from env.base import COMMON_DOCKER_RUN_COMMANDS  # noqa: E402
    from scenarios import all_scenarios            # noqa: E402

    envs = {e.id: e for e in all_envs}
    scenarios = {s.id: s for s in all_scenarios}
    out = {"scenarios": sorted(scenarios), "frameworks": sorted(envs), "tasks": {}}
    for tid in json.loads(args.tasks):
        scenario_id, _, env_id = tid.partition("@")
        scenario, env = scenarios[scenario_id], envs[env_id]
        # The same extra RUN commands test mode adds (tasks.py test_code), so the agent's
        # environment has the packages the tested app will have.
        extra = (COMMON_DOCKER_RUN_COMMANDS + scenario.needed_packages.get("_all_", [])
                 + scenario.needed_packages.get(env.language, []))
        out["tasks"][tid] = {
            "scenario": scenario_id, "framework": env_id,
            # safety_prompt="none": the arm is the only source of security guidance.
            "prompt": scenario.build_prompt(env, "openapi", "none", agent=True),
            "dockerfile": env.build_only_docker_image_file(extra),
            "manifest_files": dict(env.manifest_files),
            "workdir": env.workdir, "port": env.port,
            "is_multi_file": env.is_multi_file, "code_filename": env.code_filename,
            "functional_tests": len(scenario.functional_tests),
            "security_tests": len(scenario.security_tests),
        }
    with open(args.out, "w") as fh:
        json.dump(out, fh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
