"""evidence.jsonl: row rules, append atomicity, and weights-scan output as evidence."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import evidence as ev  # noqa: E402
import weights_scan  # noqa: E402


def _row(**over):
    row = {"id": "E001", "claim": "The system card reports a refusal rate on its own test set.",
           "threats": ["harmful-assistance"], "source": "https://example.com/system-card",
           "captured": "2026-11-10", "provenance": "published", "note": "Bare API only."}
    row.update(over)
    return row


def _file(path, status="safe", **scanners):
    return {"type": "file", "path": path, "size": 1,
            "securityFileStatus": {"status": status,
                                   **{k: {"status": v} for k, v in scanners.items()}}}


def test_valid_row_has_no_errors():
    assert ev.check_row(_row()) == ([], [])


@pytest.mark.parametrize("over,fragment", [
    ({"provenance": "vendor"}, "provenance"),
    ({"source": "the system card"}, "http(s) URL"),
    ({"captured": "10 Nov 2026"}, "YYYY-MM-DD"),
    ({"captured": (dt.date.today() + dt.timedelta(days=2)).isoformat()}, "future"),
    ({"threats": "jailbreak"}, "list of threat ids"),
    ({"threats": ["Jail Break"]}, "lower-case"),
    ({"claim": "  "}, "claim is empty"),
    ({"confidence": "high"}, "unknown field"),
    ({"kind": "rumour"}, "kind"),
])
def test_row_rules(over, fragment):
    errs, _ = ev.check_row(_row(**over))
    assert any(fragment in e for e in errs), errs


def test_missing_field_is_reported_by_name():
    row = _row()
    del row["provenance"]
    assert ev.check_row(row)[0] == ["missing field 'provenance'"]


def test_self_run_needs_a_pointer_and_may_use_a_path_as_source():
    base = dict(provenance="self_run", source=".evals/model-benchmark/x_2026-11-10/summary.md")
    assert any("pointer" in e for e in ev.check_row(_row(**base))[0])
    assert ev.check_row(_row(**base, pointer=base["source"]))[0] == []


def test_absent_row_must_say_where_you_looked():
    errs, _ = ev.check_row(_row(absent=True, note=""))
    assert any("where you looked" in e for e in errs)
    assert ev.check_row(_row(absent=True, note="Searched the vendor's trust centre."))[0] == []


def test_row_bearing_on_no_threat_is_a_warning_not_an_error():
    errs, warns = ev.check_row(_row(threats=[]))
    assert errs == [] and len(warns) == 1


def test_known_threat_list_rejects_ids_outside_it(tmp_path):
    plan = tmp_path / "test-plan.json"
    plan.write_text(json.dumps({"threats": [{"threat": "jailbreak"}, {"id": "prompt-injection"}]}))
    known = ev.load_known_threats(str(plan))
    assert known == {"jailbreak", "prompt-injection"}
    assert ev.check_row(_row(threats=["jailbreak"]), known)[0] == []
    assert any("not in the supplied" in e for e in ev.check_row(_row(), known)[0])


def test_append_assigns_sequential_ids_and_writes_nothing_on_a_bad_row(tmp_path):
    path = tmp_path / "evidence.jsonl"
    good = {k: v for k, v in _row().items() if k != "id"}
    assert [r["id"] for r in ev.append_rows(path, [good, good])] == ["E001", "E002"]
    with pytest.raises(ValueError):
        ev.append_rows(path, [good, {**good, "provenance": "guess"}])
    rows, errs = ev.read_rows(path)
    assert [r["id"] for r in rows] == ["E001", "E002"] and errs == []
    assert ev.append_rows(path, [good])[0]["id"] == "E003"


def test_validate_file_reports_duplicates_and_unparseable_lines(tmp_path):
    path = tmp_path / "evidence.jsonl"
    path.write_text(json.dumps(_row()) + "\n" + json.dumps(_row()) + "\n{broken\n")
    result = ev.validate_file(path)
    assert result["rows"] == 2
    assert any("duplicate id" in e for e in result["errors"])
    assert any("line 3" in e for e in result["errors"])


# --- open-weights harvest -> rows ---------------------------------------------------------

def test_unscanned_weights_become_an_absent_row_never_a_clean_claim():
    tree = [_file("model.safetensors", protectAiScan="safe"),
            _file("pytorch_model.bin", status="unscanned", avScan="queued")]
    result = {"repo": "org/m", "revision": "main",
              **weights_scan.assess(tree, {"scansDone": True})}
    assert result["verdict"] == "unscanned"
    rows = ev.weights_rows(result, captured="2026-11-10")
    assert len(rows) == 1 and rows[0]["absent"] is True
    assert "No complete scan result" in rows[0]["claim"]
    assert "Unscanned is not clean" in rows[0]["note"]
    assert "no issue" not in rows[0]["claim"]
    assert rows[0]["provenance"] == "harvested"
    assert rows[0]["source"] == "https://huggingface.co/org/m/tree/main"


def test_harvest_error_is_an_absent_row():
    rows = ev.weights_rows({"repo": "org/m", "revision": "main", "verdict": "error",
                            "error": "HTTP 404 listing org/m (missing, gated or private)"},
                           captured="2026-11-10")
    assert rows[0]["absent"] is True and "HTTP 404" in rows[0]["note"]


def test_clean_and_unsafe_verdicts_and_pickle_only_row():
    clean = {"repo": "org/m", "revision": "main",
             **weights_scan.assess([_file("m.safetensors", avScan="safe")], {"scansDone": True})}
    rows = ev.weights_rows(clean, captured="2026-11-10")
    assert len(rows) == 1 and rows[0]["absent"] is False
    assert "does not show the weights are free of a backdoor" in rows[0]["note"]

    unsafe = {"repo": "org/m", "revision": "main",
              **weights_scan.assess([_file("pytorch_model.bin", pickleImportScan="unsafe")],
                                    {"scansDone": True})}
    rows = ev.weights_rows(unsafe, captured="2026-11-10")
    assert "flag" in rows[0]["claim"] and "pytorch_model.bin" in rows[0]["claim"]
    assert len(rows) == 2 and "pickle-based formats" in rows[1]["claim"]


def test_every_generated_weights_row_passes_validation():
    for verdict_input in (
            {"repo": "o/m", "revision": "main", "verdict": "error", "error": "x"},
            json.loads((SKILL / "examples" / "weights.example.json").read_text())):
        for i, row in enumerate(ev.weights_rows(verdict_input, captured="2026-11-10"), 1):
            assert ev.check_row({"id": f"E{i:03d}", **row})[0] == []


def test_summary_separates_absent_rows_and_unchecked_threats(tmp_path):
    rows = [_row(), _row(id="E002", threats=["jailbreak"], provenance="self_run",
                         source="s.md", pointer="s.md"),
            _row(id="E003", threats=["data-retention-hosting"], absent=True,
                 provenance="reviewed", claim="No retention statement found.",
                 note="Searched the vendor documentation index.")]
    text = ev.summarize(rows)
    assert "absent (1)" in text and "E003: No retention statement found." in text
    section = text.split("threats whose only evidence")[1]
    assert "harmful-assistance" in section and "jailbreak" not in section


def test_cli_append_validate_from_weights(tmp_path, capsys):
    path = tmp_path / "evidence.jsonl"
    assert ev.main(["append", "--file", str(path), "--claim", "No system card was found.",
                    "--threats", "harmful-assistance,jailbreak",
                    "--source", "https://example.com/docs", "--provenance", "reviewed",
                    "--note", "Searched the documentation index and the trust centre.",
                    "--absent", "--captured", "2026-11-10"]) == 0
    assert ev.main(["from-weights", str(SKILL / "examples" / "weights.example.json"),
                    "--file", str(path), "--captured", "2026-11-10"]) == 0
    assert ev.main(["validate", str(path)]) == 0
    assert ev.main(["append", "--file", str(path), "--claim", "x", "--source", "not a url",
                    "--provenance", "published"]) == 1
    rows, _ = ev.read_rows(path)
    assert [r["id"] for r in rows] == ["E001", "E002"]
    assert rows[0]["absent"] is True and rows[1]["kind"] == "weights_scan"
    capsys.readouterr()
