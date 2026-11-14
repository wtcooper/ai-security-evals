"""Arm installation: an arm is copied as it is and never interpreted."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import arms  # noqa: E402

SKILL = Path(__file__).resolve().parents[1]


def make_arm(root: Path) -> Path:
    arm = root / "arms" / "mixed"
    files = {
        "RULES.md": b"plain text\n",
        ".agent/skills/demo/SKILL.md": b"---\nname: [broken yaml\n---\n{{ not a template }}\n",
        ".agent/settings.json": b"{ this is not valid JSON",
        "hooks/check.sh": b"#!/bin/sh\nexit 0\n",
        "blob.bin": bytes(range(256)) + b"\xff\xfe\x00",
        "_home/.config/tool/config.toml": b"key = 'value'\n",
        "arm.json": json.dumps({"control_type": "mixed"}).encode(),
    }
    for rel, data in files.items():
        path = arm / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    os.chmod(arm / "hooks/check.sh", 0o755)
    return arm


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_arm_is_copied_byte_for_byte_and_nothing_is_interpreted(tmp_path):
    arm = make_arm(tmp_path)
    ws, home = tmp_path / "ws", tmp_path / "home"
    arms.install(arm, ws, home)                 # broken YAML, broken JSON, binary: no error
    source = tree(arm)
    assert tree(ws) == {k: v for k, v in source.items()
                        if k != "arm.json" and not k.startswith("_home/")}
    assert tree(home) == {".config/tool/config.toml": source["_home/.config/tool/config.toml"]}


def test_permission_bits_survive_so_a_hook_stays_executable(tmp_path):
    arm = make_arm(tmp_path)
    ws = tmp_path / "ws"
    arms.install(arm, ws, tmp_path / "home")
    assert os.stat(ws / "hooks/check.sh").st_mode & 0o777 == 0o755
    assert os.stat(ws / "RULES.md").st_mode & 0o111 == 0


def test_label_file_is_never_installed_and_home_folder_is_routed(tmp_path):
    plan = arms.install_plan(make_arm(tmp_path), "/app", "/root")
    dests = {item["dest"]: item["root"] for item in plan}
    assert "/app/arm.json" not in dests and "/root/arm.json" not in dests
    assert dests["/root/.config/tool/config.toml"] == "home"
    assert dests["/app/.agent/skills/demo/SKILL.md"] == "workspace"
    assert not any(d.startswith("/app/_home") for d in dests)


def test_baseline_installs_nothing(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert arms.install(None, ws, tmp_path / "home") == []
    assert list(ws.iterdir()) == []


def test_discover_puts_baseline_first_and_reads_only_the_label(tmp_path):
    make_arm(tmp_path)
    (tmp_path / "arms" / "unlabelled").mkdir()
    (tmp_path / "arms" / "unlabelled" / "x.txt").write_text("x")
    found = arms.discover(tmp_path / "arms")
    assert [a["name"] for a in found] == ["baseline", "mixed", "unlabelled"]
    assert found[0]["dir"] is None and found[0]["files"] == 0
    assert found[1]["control_type"] == "mixed" and found[1]["files"] == 6
    assert found[2]["control_type"] is None


def test_folder_named_baseline_and_broken_label_are_errors(tmp_path):
    (tmp_path / "a" / "baseline").mkdir(parents=True)
    with pytest.raises(ValueError, match="implicit"):
        arms.discover(tmp_path / "a")
    (tmp_path / "b" / "arm1").mkdir(parents=True)
    (tmp_path / "b" / "arm1" / "arm.json").write_text("{nope")
    with pytest.raises(ValueError, match="not valid JSON"):
        arms.discover(tmp_path / "b")


def test_fingerprint_changes_with_any_byte_and_ignores_the_label(tmp_path):
    arm = make_arm(tmp_path)
    before = arms.fingerprint(arm)
    (arm / "arm.json").write_text(json.dumps({"control_type": "renamed"}))
    assert arms.fingerprint(arm) == before
    (arm / "RULES.md").write_bytes(b"plain text!\n")
    assert arms.fingerprint(arm) != before


def test_symlink_out_of_the_arm_is_refused(tmp_path):
    arm = make_arm(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("host file")
    os.symlink(secret, arm / "leak.txt")
    with pytest.raises(ValueError, match="outside the arm folder"):
        arms.install_plan(arm, "/app", "/root")


def test_the_only_shipped_arm_is_a_labelled_placebo():
    shipped = sorted(p.name for p in (SKILL / "arms").iterdir() if p.is_dir())
    assert shipped == ["placebo"]
    assert "placebo" in arms.read_label(SKILL / "arms" / "placebo")["control_type"]
