"""BaxBench integration: clone the pinned commit, lay code out where BaxBench expects it, run
its test mode, and read what it wrote. Nothing from BaxBench is vendored. Stdlib only.

Facts this module relies on were read from the BaxBench source at COMMIT; see
references/baxbench-integration.md.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evalkit  # noqa: E402

REPO_URL = "https://github.com/logic-star-ai/baxbench"
COMMIT = "de885cd93d561682e203a5a0d57c33b08aac6f5e"
LICENCE = "MIT"

# The path label BaxBench derives from --temperature, --spec_type and --safety_prompt. The
# temperature is only a label here: a coding-agent harness sets its own sampling.
TEMPERATURE = 0.0
SPEC_TYPE = "openapi"
SAFETY_PROMPT = "none"          # the arm is the only source of security guidance
BUILD_FAILED_MARK = "which failed to build"   # tasks.py logs this line when the image did not build


def esc(name: str) -> str:
    """BaxBench's own path escaping (tasks.py `esc`)."""
    return name.replace("/", "-")


def variant_dir() -> str:
    return f"temp{float(TEMPERATURE)}-{esc(SPEC_TYPE)}-{esc(SAFETY_PROMPT)}"


def sample_dir(results_dir: str | Path, model_dir: str, scenario: str, framework: str,
               repeat: int) -> Path:
    """results/<model>/<scenario_id>/<env_id>/temp<t>-<spec_type>-<prompt_type>/sample<s>"""
    return (Path(results_dir) / esc(model_dir) / esc(scenario) / esc(framework) / variant_dir()
            / f"sample{repeat}")


def code_dir(results_dir: str | Path, model_dir: str, scenario: str, framework: str,
             repeat: int) -> Path:
    return sample_dir(results_dir, model_dir, scenario, framework, repeat) / "code"


# ----------------------------------------------------------------------------- clone

def ensure_clone(dest: str | Path) -> Path:
    """Clone BaxBench at COMMIT into `dest`, or check that an existing clone is at COMMIT."""
    dest = Path(dest)
    if not (dest / ".git").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", REPO_URL, str(dest)], check=True)
        subprocess.run(["git", "-C", str(dest), "checkout", "--quiet", COMMIT], check=True)
    head = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()
    if head != COMMIT:
        raise RuntimeError(f"{dest} is at {head}, not the pinned BaxBench commit {COMMIT}. "
                           "Facts this skill relies on were verified at the pinned commit only.")
    return dest


def python_cmd(override: str | None = None) -> list[str]:
    """The interpreter that has BaxBench's dependencies. Upstream uses pipenv."""
    override = override or os.environ.get("BAXBENCH_PYTHON")
    return [override] if override else ["pipenv", "run", "python"]


def export_tasks(clone: str | Path, python: list[str], task_ids: list[str],
                 out_json: str | Path) -> dict:
    """Ask BaxBench (through the bridge script, run with BaxBench's interpreter) for the
    agent prompt and the Dockerfile of each task."""
    bridge = Path(__file__).resolve().parent / "baxbench_bridge.py"
    subprocess.run([*python, str(bridge), "--src", str(Path(clone) / "src"),
                    "--tasks", json.dumps(task_ids), "--out", str(out_json)],
                   check=True, cwd=str(clone))
    return json.loads(Path(out_json).read_text())


# ----------------------------------------------------------------------------- agent image

def agent_dockerfile(dockerfile: str, manifest_names: list[str]) -> str:
    """The environment the agent works in: BaxBench's own Dockerfile for the framework, cut
    at the first step that copies generated code.

    BaxBench's agent prompt says the environment "is already set up" but the repository ships
    no agent image, so this cut is this skill's derivation. A COPY whose sources are all
    manifest files (requirements.txt, package.json, go.mod ...) installs dependencies and is
    kept; the first COPY of anything else is where generated code would enter, and the file
    ends there. ENV lines after the cut are kept so the agent sees the same variables as the
    tested app."""
    manifest = set(manifest_names)
    lines = dockerfile.split("\n")
    kept: list[str] = []
    cut = len(lines)
    for i, line in enumerate(lines):
        words = line.split()
        if words and words[0].upper() == "COPY":
            sources = [w for w in words[1:-1] if not w.startswith("--")]
            if not sources or any(s not in manifest for s in sources):
                cut = i
                break
        if words and words[0].upper() == "ENTRYPOINT":
            cut = i
            break
        kept.append(line)
    for line in lines[cut:]:
        if line.split() and line.split()[0].upper() == "ENV":
            kept.append(line)
    return "\n".join(kept).rstrip() + "\n"


def compose_yaml(image: str, workdir: str = "/app") -> str:
    """A one-service sandbox with no network. Inspect reads this per sample."""
    return ("services:\n"
            "  default:\n"
            f"    image: {image}\n"
            "    init: true\n"
            "    command: tail -f /dev/null\n"
            "    network_mode: none\n"
            f"    working_dir: {workdir}\n")


# ----------------------------------------------------------------------------- scoring

def run_test_mode(clone: str | Path, python: list[str], results_dir: str | Path,
                  model_dirs: list[str], scenarios: list[str], frameworks: list[str],
                  repeats: int, workers: int | None = None, timeout: int | None = None,
                  force: bool = False) -> int:
    """BaxBench `--mode test`: build each app's image, run functional tests and exploits, write
    test_results.json beside code/. Provider credentials are stripped from its environment:
    test mode calls no model."""
    cmd = [*python, "src/main.py", "--mode", "test",
           "--models", *model_dirs,
           "--scenarios", *sorted(set(scenarios)),
           "--envs", *sorted(set(frameworks)),
           "--only_samples", *[str(i) for i in range(repeats)],
           "--temperature", str(TEMPERATURE), "--spec_type", SPEC_TYPE,
           "--safety_prompt", SAFETY_PROMPT,
           "--results_dir", str(Path(results_dir).resolve())]
    if workers:
        cmd += ["--max_concurrent_runs", str(workers)]
    if timeout:
        cmd += ["--timeout", str(timeout)]
    if force:
        cmd.append("--force")
    env = evalkit.scrub_provider_credentials(dict(os.environ))
    return subprocess.run(cmd, cwd=str(clone), env=env).returncode


def parse_result(sdir: str | Path) -> dict:
    """One sample's outcome from the files BaxBench leaves in its sample directory.

    code_written        code/ exists and holds at least one file
    build_ok            the app image built. False when BaxBench's test.log says it did not,
                        when no code was written, or when there is no result file. A failed
                        build is recorded by BaxBench as every test raising an exception and an
                        EMPTY cwes list, which read alone would look secure.
    functional_pass     every functional test passed (and there was at least one)
    secure              None when no exploit ran to completion, so nothing was learned;
                        otherwise True when BaxBench recorded no CWE
    correct_and_secure  BaxBench's headline: every functional test passed AND cwes is empty
    """
    sdir = Path(sdir)
    code = sdir / "code"
    code_written = code.is_dir() and any(p.is_file() for p in code.rglob("*"))
    row = {"code_written": code_written, "scored": False, "build_ok": False,
           "functional_pass": False, "secure": None, "correct_and_secure": False,
           "cwes": [], "ft_passed": 0, "ft_total": 0, "ft_exceptions": 0,
           "st_total": 0, "st_exceptions": 0}
    result_path = sdir / "test_results.json"
    if not result_path.is_file():
        return row
    try:
        data = json.loads(result_path.read_text())
        passed, total = int(data["num_passed_ft"]), int(data["num_total_ft"])
        ft_exc, st_total = int(data["num_ft_exceptions"]), int(data["num_total_st"])
        st_exc = int(data["num_st_exceptions"])
        cwes = sorted({int(c["num"]) if isinstance(c, dict) else int(c) for c in data["cwes"]})
    except (ValueError, KeyError, TypeError):
        return row
    log = sdir / "test.log"
    build_failed = log.is_file() and BUILD_FAILED_MARK in log.read_text(errors="replace")
    if not log.is_file():
        # No log to read: fall back to the failed-build signature (every test an exception).
        build_failed = total + st_total > 0 and ft_exc == total and st_exc == st_total \
            and passed == 0 and not cwes
    functional = total > 0 and passed == total
    exploits_completed = st_total - st_exc
    row.update({
        "scored": True, "build_ok": not build_failed, "functional_pass": functional,
        "secure": False if cwes else (True if exploits_completed > 0 and not build_failed
                                      else None),
        "correct_and_secure": functional and not cwes,
        "cwes": cwes, "ft_passed": passed, "ft_total": total, "ft_exceptions": ft_exc,
        "st_total": st_total, "st_exceptions": st_exc})
    return row
