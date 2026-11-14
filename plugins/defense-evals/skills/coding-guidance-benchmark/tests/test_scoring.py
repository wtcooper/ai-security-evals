"""Reading what BaxBench's test mode leaves behind, including a build that failed."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import baxbench  # noqa: E402
import fake_scorer  # noqa: E402
import mock_harness  # noqa: E402

CWE_94 = {"num": 94, "desc": "code injection"}        # the shape tasks.py to_dict() writes
CWE_400 = {"num": 400, "desc": "resource consumption"}


def sample(tmp_path: Path, result: dict | None, log: str | None = "INFO saved test results\n",
           code: bool = True) -> Path:
    sdir = tmp_path / "sample0"
    sdir.mkdir()
    if code:
        (sdir / "code").mkdir()
        (sdir / "code" / "app.py").write_text("print('app')\n")
    if result is not None:
        (sdir / "test_results.json").write_text(json.dumps(result))
    if log is not None:
        (sdir / "test.log").write_text(log)
    return sdir


def result(passed=2, total=2, ft_exc=0, st_total=3, st_exc=0, cwes=()):
    return {"num_passed_ft": passed, "num_total_ft": total, "num_ft_exceptions": ft_exc,
            "num_total_st": st_total, "num_st_exceptions": st_exc, "cwes": list(cwes)}


def test_correct_and_secure(tmp_path):
    row = baxbench.parse_result(sample(tmp_path, result()))
    assert row["build_ok"] and row["functional_pass"] and row["secure"] is True
    assert row["correct_and_secure"] is True and row["cwes"] == []


def test_working_app_with_an_exploit_is_not_correct_and_secure(tmp_path):
    row = baxbench.parse_result(sample(tmp_path, result(cwes=[CWE_94, CWE_400])))
    assert row["functional_pass"] and row["secure"] is False and not row["correct_and_secure"]
    assert row["cwes"] == [94, 400]


def test_app_that_fails_its_tests_is_not_correct_even_with_no_cwe(tmp_path):
    row = baxbench.parse_result(sample(tmp_path, result(passed=1)))
    assert not row["functional_pass"] and row["secure"] is True and not row["correct_and_secure"]


def test_failed_build_is_not_secure_although_cwes_is_empty(tmp_path):
    """BaxBench writes every test as an exception and an empty cwes list for an image that
    did not build. Read naively that is 'no weakness found'."""
    failed = result(passed=0, ft_exc=2, st_exc=3)
    log = "ERROR Failed to build docker image\nINFO Finished testing sample 0, which failed to build\n"
    row = baxbench.parse_result(sample(tmp_path, failed, log))
    assert row["scored"] and row["build_ok"] is False
    assert row["secure"] is None and row["correct_and_secure"] is False
    assert row["cwes"] == [] and row["st_exceptions"] == 3


def test_failed_build_is_recognised_without_a_log(tmp_path):
    row = baxbench.parse_result(sample(tmp_path, result(passed=0, ft_exc=2, st_exc=3), log=None))
    assert row["build_ok"] is False and row["secure"] is None


def test_app_that_built_but_never_answered_has_unknown_security(tmp_path):
    row = baxbench.parse_result(sample(tmp_path, result(passed=0, ft_exc=2, st_exc=3)))
    assert row["build_ok"] is True and row["secure"] is None and not row["correct_and_secure"]


def test_exploit_that_could_not_complete_is_kept_visible(tmp_path):
    row = baxbench.parse_result(sample(tmp_path, result(st_exc=1)))
    assert row["correct_and_secure"] is True        # BaxBench's own definition
    assert row["secure"] is True and row["st_exceptions"] == 1


def test_no_code_and_no_result_file(tmp_path):
    row = baxbench.parse_result(sample(tmp_path, None, log=None, code=False))
    assert row == {**row, "code_written": False, "scored": False, "build_ok": False,
                   "functional_pass": False, "secure": None, "correct_and_secure": False}
    (tmp_path / "x").mkdir()
    row = baxbench.parse_result(sample(tmp_path / "x", None, log=None, code=True))
    assert row["code_written"] and not row["scored"]


def test_unreadable_result_file_counts_as_not_scored(tmp_path):
    sdir = sample(tmp_path, None)
    (sdir / "test_results.json").write_text("{broken")
    assert baxbench.parse_result(sdir)["scored"] is False


def test_results_layout_matches_baxbench(tmp_path):
    path = baxbench.code_dir("results", "claude_code__some-model__baseline", "Calculator",
                             "Go-net/http", 3)
    assert path.as_posix() == ("results/claude_code__some-model__baseline/Calculator/Go-net-http/"
                               "temp0.0-openapi-none/sample3/code")


def test_agent_dockerfile_stops_before_generated_code_is_copied():
    dockerfile = "\n".join([
        "FROM base:1", "RUN apt-get update", "WORKDIR /app",
        "COPY requirements.txt requirements.txt", "RUN pip install -r requirements.txt",
        "ENV APP_SECRET=supers3cret", "COPY / /app/", "RUN python manage.py migrate",
        "ENTRYPOINT python3 app.py"])
    cut = baxbench.agent_dockerfile(dockerfile, ["requirements.txt"])
    assert "COPY requirements.txt requirements.txt" in cut and "pip install" in cut
    assert "COPY / /app/" not in cut and "ENTRYPOINT" not in cut and "migrate" not in cut
    assert "ENV APP_SECRET=supers3cret" in cut


def test_agent_dockerfile_keeps_env_set_after_the_cut():
    dockerfile = "\n".join([
        "FROM golang:1", "WORKDIR /app", "COPY go.mod build_helper.go ./", "RUN go build .",
        "COPY * ./", "RUN go build . || echo failed", "ENV APP_SECRET=supers3cret",
        "ENTRYPOINT ./myapp"])
    cut = baxbench.agent_dockerfile(dockerfile, ["go.mod", "build_helper.go"])
    assert cut.count("COPY") == 1 and cut.rstrip().endswith("ENV APP_SECRET=supers3cret")
    assert "ENTRYPOINT" not in cut


def test_sandbox_has_no_network():
    assert "network_mode: none" in baxbench.compose_yaml("image:tag")


def test_fake_scorer_writes_what_the_real_parser_reads(tmp_path):
    expect = {"route": "/hello", "reply": "hello"}
    outcomes = {}
    for variant in ("good", "insecure", "broken", "nobuild"):
        sdir = tmp_path / variant / "sample0"
        (sdir / "code").mkdir(parents=True)
        (sdir / "code" / "app.json").write_text(mock_harness.fake_app(expect, variant))
        fake_scorer.score(sdir, expect)
        row = baxbench.parse_result(sdir)
        outcomes[variant] = (row["build_ok"], row["functional_pass"], row["secure"],
                             row["correct_and_secure"])
    assert outcomes == {"good": (True, True, True, True),
                        "insecure": (True, True, False, False),
                        "broken": (True, False, True, False),
                        "nobuild": (False, False, None, False)}
