"""The repo is a set of Agent Plugins: manifests, skill frontmatter and generated files."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import check_plugins  # noqa: E402
import gen_manifests  # noqa: E402

GOOD = {"$schema": check_plugins.PLUGIN_SCHEMA, "name": "demo"}


def _plugin(tmp_path, manifest, frontmatter="name: do-thing\ndescription: Does a thing."):
    plugin = tmp_path / "plugins" / "demo"
    skill = plugin / "skills" / "do-thing"
    skill.mkdir(parents=True)
    (plugin / "plugin.json").write_text(json.dumps(manifest))
    (skill / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n# body\n")
    return tmp_path


def test_the_repo_itself_conforms():
    assert check_plugins.check_repo() == []


def test_generated_manifests_are_current():
    assert all((ROOT / rel).read_text() == text for rel, text in gen_manifests.build().items())


def test_every_plugin_is_listed_in_the_marketplace_with_a_relative_source():
    market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
    names = sorted(p.parent.name for p in ROOT.glob("plugins/*/plugin.json"))
    assert sorted(e["name"] for e in market["plugins"]) == names
    assert all(e["source"] == f"./plugins/{e['name']}" for e in market["plugins"])
    assert all("version" not in e for e in market["plugins"])


def test_minimal_plugin_passes(tmp_path):
    assert check_plugins.check_repo(_plugin(tmp_path, GOOD)) == []


def test_manifest_schema_is_closed_and_name_rules_hold(tmp_path):
    errs = check_plugins.check_repo(_plugin(tmp_path, {**GOOD, "hooks": {}}))
    assert any("unknown field 'hooks'" in e for e in errs)
    for bad in ("Demo", "de--mo", "-demo", "demo.", "x" * 65):
        assert check_plugins.check_manifest(_write(tmp_path / bad[:8], {**GOOD, "name": bad}))
    assert any("$schema" in e for e in check_plugins.check_manifest(
        _write(tmp_path / "noschema", {"name": "noschema"})))


def _write(directory, manifest):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "plugin.json"
    path.write_text(json.dumps(manifest))
    return path


def test_manifest_name_must_match_directory(tmp_path):
    errs = check_plugins.check_repo(_plugin(tmp_path, {**GOOD, "name": "other"}))
    assert any("does not match directory" in e for e in errs)


def test_client_specific_frontmatter_is_rejected(tmp_path):
    fm = "name: do-thing\ndescription: Does a thing.\ndisable-model-invocation: true"
    errs = check_plugins.check_repo(_plugin(tmp_path, GOOD, fm))
    assert any("non-standard frontmatter field 'disable-model-invocation'" in e for e in errs)


def test_skill_name_and_description_rules(tmp_path):
    errs = check_plugins.check_repo(_plugin(tmp_path, GOOD, "name: other\ndescription: x"))
    assert any("does not match directory" in e for e in errs)
    long = "name: do-thing\ndescription: >-\n  " + "word " * 300
    errs = check_plugins.check_repo(_plugin(tmp_path / "b", GOOD, long))
    assert any("description is" in e and "limit 1024" in e for e in errs)


def test_folded_description_is_parsed_as_one_value():
    fm = check_plugins.parse_frontmatter(
        "---\nname: a\ndescription: >-\n  first line\n  second: line\nlicense: MIT\n---\n")
    assert fm == {"name": "a", "description": "first line second: line", "license": "MIT"}


def test_symlink_out_of_the_plugin_is_rejected(tmp_path):
    root = _plugin(tmp_path, GOOD)
    (tmp_path / "outside.txt").write_text("x")
    (root / "plugins" / "demo" / "link").symlink_to(tmp_path / "outside.txt")
    assert any("outside the plugin root" in e for e in check_plugins.check_repo(root))
