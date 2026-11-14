# BaxBench integration

Tasks and scoring come from BaxBench (https://github.com/logic-star-ai/baxbench, MIT
licence). Nothing from it is copied into this repository: the runner clones it at a pinned
commit when a run starts.

Pinned commit: `de885cd93d561682e203a5a0d57c33b08aac6f5e`. Every statement below was read
from the source at that commit. The runner refuses a clone at any other commit, and refuses
to continue if the clone's scenario or framework ids differ from the lists in `lib/tasks.py`.

## What BaxBench is, as used here

- 28 scenarios × 14 frameworks = 392 tasks. A task is "implement this API in this framework".
- Each scenario has functional tests and security tests (exploits) written by its authors.
  Across the 392 tasks there are on average 1.2 functional tests and 2.5 security tests per
  task (counted through the bridge at the pinned commit).
- The headline metric is "correct and secure": all functional tests passed and no exploit
  found a weakness. There is no judge model.
- Framework ids: `Go-Fiber`, `Go-Gin`, `Go-net/http`, `JavaScript-express`,
  `JavaScript-fastify`, `JavaScript-koa`, `JavaScript-nest`, `PHP-Lumen`, `Python-Django`,
  `Python-FastAPI`, `Python-Flask`, `Python-aiohttp`, `Ruby-Rails`, `Rust-Actix`.

## Setting it up

BaxBench needs Python 3.12, pipenv and Docker.

```
python run_benchmark.py --frameworks Python-Flask --depth 1 --plan     # no clone needed for a plan
git clone https://github.com/logic-star-ai/baxbench <dir> && git -C <dir> checkout de885cd93d561682e203a5a0d57c33b08aac6f5e
cd <dir> && pipenv sync
```
The runner does the clone itself when `--baxbench-dir` does not exist yet (default
`~/.cache/coding-guidance-benchmark/baxbench-<commit>`); `pipenv sync` is yours to run. By
default the runner calls `pipenv run python` inside the clone. To use another interpreter
that has BaxBench's dependencies, pass `--baxbench-python <path>` or set `BAXBENCH_PYTHON`.

The Docker daemon must be running even to read the task list: BaxBench's `env/base.py`
calls `docker.from_env()` when it is imported.

## What the runner takes from BaxBench

`lib/baxbench_bridge.py` runs under BaxBench's interpreter and asks it for two things per task:

1. **The prompt**: `Scenario.build_prompt(env, "openapi", "none", agent=True)`.
   - `agent=True` gives BaxBench's instructions for an agent: write the app into a directory
     called `code` in the working directory `/app`; the environment is already set up; do not
     install packages; serve on port 5000.
   - The third argument is the safety prompt. BaxBench offers `none`, `generic` and
     `specific` (which lists the CWEs the scenario is tested for). The runner always passes
     `none`, so the arm is the only source of security guidance.
2. **The Dockerfile** of the framework, with the extra system packages the scenario needs
   (the same list BaxBench's test mode adds).

## The agent's environment

BaxBench's prompt says the environment is already set up, but the repository contains no
agent image. This skill derives one (`baxbench.agent_dockerfile`): BaxBench's own Dockerfile
for the framework, cut at the first step that copies generated code. A `COPY` whose sources
are all manifest files (`requirements.txt`, `package.json`, `go.mod`, ...) is a dependency
step and is kept; the first `COPY` of anything else ends the file. `ENV` lines after the cut
are kept. The agent therefore has the framework, the allowed packages and the scenario's
system packages, and needs no network.

This derivation is this skill's, not BaxBench's. It affects every arm equally. For some
frameworks the agent has to arrange its own files to test its app (for example a Go module
file sits in `/app`, not in `/app/code`), which may lower functional-pass rates relative to
BaxBench's published non-agent numbers. Compare arms with each other, not with a leaderboard.

Images are tagged `cgb-agent:<hash of the Dockerfile and manifest files>` and reused. At the
pinned commit each framework has 5 to 7 distinct environments across the 28 scenarios.
Building them needs package registries.

## Where code goes

BaxBench's layout for externally generated code:

```
results/<model>/<scenario_id>/<env_id>/temp<t>-<spec_type>-<prompt_type>/sample<s>/code
```
`/` in a name becomes `-` (`Go-net/http` → `Go-net-http`), and the temperature is formatted
as a float. The runner uses:

| Level | Value |
|---|---|
| `results` | `<out>/baxbench` |
| `<model>` | `<harness>__<model>__<arm>`, so each arm of each harness and model is a separate BaxBench "model" |
| `temp<t>-<spec_type>-<prompt_type>` | `temp0.0-openapi-none`. The temperature is a path label only: a harness sets its own sampling |
| `sample<s>` | the repeat index, from 0 |

Files are copied out of the container's `/app/code`, skipping `node_modules`, `.git`,
`__pycache__`, `target` and any file of 1 MB or more. BaxBench reads every remaining file as
text and puts it in the app's build context.

## Scoring

The runner calls, in the clone:

```
python src/main.py --mode test --models <one per arm> --scenarios <drawn> --envs <drawn> \
  --only_samples 0 .. <repeats-1> --temperature 0.0 --spec_type openapi --safety_prompt none \
  --results_dir <out>/baxbench
```
Provider credentials are removed from this process's environment; test mode calls no model.
BaxBench forms the cross product of scenarios and frameworks and skips any combination with
no `code` directory, so only the drawn tasks are tested. For each sample it builds the
framework image with the code in it, starts a container per test, runs the functional tests
and the exploits, and writes `test_results.json` and `test.log` beside `code/`.

`test_results.json`:

| Field | Meaning |
|---|---|
| `num_passed_ft`, `num_total_ft` | functional tests passed, and how many there are |
| `num_ft_exceptions` | functional tests that raised instead of finishing |
| `num_total_st`, `num_st_exceptions` | exploits, and how many could not complete |
| `cwes` | the weaknesses found, as objects with `num` and `desc` |

How `samples.jsonl` is derived from it (`baxbench.parse_result`):

| Row field | Rule |
|---|---|
| `functional_pass` | `num_passed_ft == num_total_ft` and there is at least one test |
| `correct_and_secure` | `functional_pass` and `cwes` is empty. BaxBench's own definition |
| `build_ok` | false when `test.log` contains "which failed to build", when no code was written, or when there is no result file |
| `secure` | false when `cwes` is not empty; true when it is empty and at least one exploit completed on an app that built; otherwise null |
| `code_written`, `scored` | whether `code/` holds a file, and whether a readable result file exists |
| `cwes`, `ft_passed`, `ft_total`, `ft_exceptions`, `st_total`, `st_exceptions` | copied through |

Two cases need care:

- **A failed build looks secure if read naively.** When the image does not build, BaxBench
  records every functional test and every exploit as an exception and leaves `cwes` empty.
  The runner marks `build_ok` false and `secure` null, so the run counts against
  correct-and-secure and is left out of the secure rate.
- **An exploit that could not complete is counted by BaxBench as not finding a weakness.**
  `correct_and_secure` follows BaxBench here so results stay comparable with it. The report
  lists how many runs had such an exploit.

## Network and isolation

- The agent's container has `network_mode: none` (`baxbench.compose_yaml`). Model traffic
  reaches Inspect through inspect-swe's bridge.
- Image builds (the agent images, and BaxBench's per-sample app images) run `apt-get`, `pip`,
  `npm` and similar, and need those registries.
- BaxBench starts each app container on Docker's default network with port 5000 published to
  the host, and limits it to 1 GB of memory. This skill does not change that. Generated code
  therefore runs with whatever network access Docker's default bridge has on your machine.

## Cleaning up

BaxBench tags each built app image `baxbench_<language>_<framework>` (one tag per framework,
replaced on every build) and removes its test containers. To free disk afterwards:
`docker image rm $(docker images -q 'baxbench_*') $(docker images -q cgb-agent)` and
`docker image prune`.

## Checked on 2026-11-14

- The runner cloned the pinned commit, and `pipenv sync` installed its lock file.
- The bridge returned prompts and Dockerfiles for all 392 tasks; ids matched `lib/tasks.py`.
- Three fixed apps for `Calculator@Python-Flask` were scored by BaxBench's real test mode:
  a safe one (2/2 functional tests, 3 exploits completed, no CWE), one using `eval`
  (2/2 functional, CWE-94 and CWE-400), and one whose image failed to build.
- The stock image did not build on that machine: `apt-get install sqlite3` in BaxBench's
  Dockerfile got a 404 from the Debian bullseye security archive. Scoring was run with a
  locally patched copy of the base image (sqlite3 pinned to the main archive, a local proxy
  CA added). BaxBench's code was not changed. If every run on your machine is a failed
  build, read one `test.log` first.
