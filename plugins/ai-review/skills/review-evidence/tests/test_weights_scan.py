"""Open-weights scan harvest: verdict rules. "Not scanned" must never read as "clean"."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import weights_scan  # noqa: E402


def _file(path, status="safe", **scanners):
    return {"type": "file", "path": path, "size": 1,
            "securityFileStatus": {"status": status,
                                   **{k: {"status": v} for k, v in scanners.items()}}}


def test_weights_clean_requires_scans_done_and_every_weight_file_scanned():
    tree = [_file("model.safetensors", protectAiScan="safe", avScan="safe")]
    assert weights_scan.assess(tree, {"scansDone": True})["verdict"] == "clean"
    assert weights_scan.assess(tree, {})["verdict"] == "unscanned"
    assert weights_scan.assess(tree, {"scansDone": False})["verdict"] == "unscanned"
    unscanned = [_file("model.safetensors", status="unscanned", avScan="queued")]
    assert weights_scan.assess(unscanned, {"scansDone": True})["verdict"] == "unscanned"
    assert weights_scan.assess([], {"scansDone": True})["verdict"] == "unscanned"


def test_weights_any_scanner_or_summary_issue_is_unsafe():
    tree = [_file("pytorch_model.bin", protectAiScan="safe", pickleImportScan="unsafe")]
    result = weights_scan.assess(tree, {"scansDone": True})
    assert result["verdict"] == "unsafe" and result["unsafe_files"] == ["pytorch_model.bin"]
    assert result["pickle_only"] is True
    clean_tree = [_file("m.safetensors", avScan="safe")]
    flagged = weights_scan.assess(clean_tree, {"scansDone": True,
                                               "filesWithIssues": [{"path": "evil.pkl"}]})
    assert flagged["verdict"] == "unsafe" and "evil.pkl" in flagged["unsafe_files"]


def test_weights_coverage_counts_only_scanners_that_looked():
    tree = [_file("a.safetensors", avScan="safe", jFrogScan="unscanned"),
            _file("b.bin", avScan="safe"), _file("config.json", avScan="safe")]
    result = weights_scan.assess(tree, {"scansDone": True})
    assert result["weight_files"] == 2
    assert result["scanner_coverage"]["avScan"] == 2
    assert result["scanner_coverage"]["jFrogScan"] == 0
    assert result["pickle_only"] is False
