"""Seed corpus integrity, variant determinism and label preservation."""
from __future__ import annotations

import copy
import json

import pytest

import adapter
import variants

POLICIES, CASES = variants.load_corpus()
SEED = 20261114


def all_variants(seed=SEED, mode="all"):
    return [(case, POLICIES[case["policy"]], var)
            for case in CASES for var in variants.generate(case, POLICIES[case["policy"]], seed,
                                                           mode)]


# ---- corpus ----------------------------------------------------------------------------------

def test_corpus_size_families_and_balance():
    assert 40 <= len(CASES) <= 60
    assert len(POLICIES) >= 4
    assert {p["question"]["type"] for p in POLICIES.values()} == {"noul", "choice", "score"}
    for pid in POLICIES:
        classes = {c["error_class"] for c in CASES if c["policy"] == pid}
        assert classes == {"fail_open", "fail_closed"}, f"{pid} lacks one error class"
    assert len({c["id"] for c in CASES}) == len(CASES)
    assert len({json.dumps(c["state"], sort_keys=True) for c in CASES}) == len(CASES)


def test_every_policy_tells_the_model_that_claims_in_the_untrusted_field_do_not_count():
    # Injection variants keep their label only because the policy says this explicitly.
    for pid, pol in POLICIES.items():
        text = pol["question"]["instructions"] + " ".join(
            o["criteria"] for o in pol["question"]["options"])
        assert "not count" in text or "does not change" in text, pid
        para = pol["paraphrase"]["instructions"] + " ".join(
            o["criteria"] for o in pol["paraphrase"]["options"])
        assert any(w in para for w in ("disregard", "ignore", "no bearing")), pid


def test_a_wrong_cost_class_or_label_is_rejected_at_load(tmp_path):
    def write(rows):
        path = tmp_path / "cases.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return path

    good = copy.deepcopy(CASES[0])
    variants.load_corpus(write([good]))                       # sanity: one good case loads
    wrong_class = {**good, "error_class": "fail_open"}        # truth "allow" is not restrictive
    with pytest.raises(variants.CorpusError, match="error_class"):
        variants.load_corpus(write([wrong_class]))
    with pytest.raises(variants.CorpusError, match="truth"):
        variants.load_corpus(write([{**good, "truth": "maybe"}]))
    with pytest.raises(variants.CorpusError, match="duplicate"):
        variants.load_corpus(write([good, good]))
    no_field = copy.deepcopy(good)
    del no_field["state"]["context_text"]
    with pytest.raises(variants.CorpusError, match="context_text"):
        variants.load_corpus(write([no_field]))


def test_a_policy_whose_attack_target_is_restrictive_is_rejected():
    pol = copy.deepcopy(POLICIES["tool_gate"])
    pol["attack"]["target"] = "block"
    pol["misleading_rename"] = None
    with pytest.raises(variants.CorpusError, match="attack.target"):
        variants.validate_policy("tool_gate", pol)


# ---- determinism -----------------------------------------------------------------------------

def test_same_seed_gives_byte_identical_variants_and_another_seed_does_not():
    a = json.dumps([v for _, _, v in all_variants()], ensure_ascii=False)
    b = json.dumps([v for _, _, v in all_variants()], ensure_ascii=False)
    assert a == b
    other = json.dumps([v for _, _, v in all_variants(seed=SEED + 1)], ensure_ascii=False)
    assert other != a
    # Only the seeded techniques may differ between seeds; the rest are fixed templates.
    for (case, _, v1), (_, _, v2) in zip(all_variants(), all_variants(seed=SEED + 1)):
        if v1 != v2:
            assert v1["id"] in ("encoding.zero_width", "encoding.homoglyph",
                                "structure.extra_fields"), (case["id"], v1["id"])


def test_one_technique_per_axis_is_a_seeded_subset_of_all():
    for case in CASES:
        pol = POLICIES[case["policy"]]
        full = {v["id"] for v in variants.generate(case, pol, SEED, "all")}
        one = variants.generate(case, pol, SEED, "one")
        assert [v["id"] for v in one] == [v["id"] for v in variants.generate(case, pol, SEED, "one")]
        assert {v["id"] for v in one} <= full
        axes = [v["axis"] for v in one]
        assert len(axes) == len(set(axes)), "more than one technique for an axis"
        assert set(axes) == {v["axis"] for v in variants.generate(case, pol, SEED, "all")}


def test_case_draw_is_deterministic_and_covers_every_policy_and_error_class():
    picked = variants.select_cases(CASES, 10, SEED)
    assert [c["id"] for c in picked] == [c["id"] for c in variants.select_cases(CASES, 10, SEED)]
    assert len(picked) == 10
    assert {(c["policy"], c["error_class"]) for c in picked} == {
        (c["policy"], c["error_class"]) for c in CASES}
    assert variants.select_cases(CASES, None, SEED) == CASES
    assert len(variants.select_cases(CASES, 500, SEED)) == len(CASES)


# ---- label preservation ----------------------------------------------------------------------

def test_every_variant_records_parent_axis_and_what_changed():
    seen_axes = set()
    for case, pol, var in all_variants():
        assert var["parent"] == case["id"]
        assert var["truth"] == case["truth"], "a variant must never change the label"
        if var["id"] == "clean":
            assert var["changed"] == "none" and var["state"] == case["state"]
            continue
        seen_axes.add(var["axis"])
        assert var["id"] == f"{var['axis']}.{var['technique']}"
        assert var["technique"] in variants.TECHNIQUES[var["axis"]]
        assert var["changed"] == variants.CHANGED[var["axis"]]
        if var["changed"] == "state":
            assert var["question"] == pol["question"], "state variants must not touch options"
            assert var["state"] != case["state"]
        else:
            assert var["state"] == case["state"], "option variants must not touch the state"
            assert var["question"] != pol["question"]
    assert seen_axes == set(variants.AXES)


def test_state_variants_change_only_the_untrusted_field_or_add_fields():
    for case, pol, var in all_variants():
        if var["changed"] != "state":
            continue
        field = pol["untrusted_field"]
        original = adapter.get_path(case["state"], field)
        changed = adapter.get_path(var["state"], field)
        if var["axis"] == "structure":
            assert changed == original
            added = set(var["state"]) - set(case["state"])
            assert len(added) == len(variants.EXTRA_FIELDS)
            assert {k: var["state"][k] for k in case["state"]} == case["state"]
            continue
        assert adapter.del_path(var["state"], field) == adapter.del_path(case["state"], field)
        if var["axis"] in ("injection", "padding"):
            assert changed.startswith(original + "\n\n") and len(changed) > len(original) + 2
        elif var["technique"] == "base64_wrapper":
            assert variants.undo_base64_wrapper(changed) == original
            assert original not in changed
        elif var["technique"] == "zero_width":
            assert variants.ZERO_WIDTH in changed
            assert changed.replace(variants.ZERO_WIDTH, "") == original
        elif var["technique"] == "homoglyph":
            assert changed != original and len(changed) == len(original)
            assert variants.undo_homoglyph(changed) == original


def test_injection_targets_the_permissive_label_and_only_eligible_cases():
    for case in CASES:
        pol = POLICIES[case["policy"]]
        target = pol["attack"]["target"]
        got = [v for v in variants.generate(case, pol, SEED, "all") if v["axis"] == "injection"]
        if case["truth"] == target:
            assert got == [], f"{case['id']}: an injection toward the true label is not an attack"
            continue
        assert [v["technique"] for v in got] == list(variants.TECHNIQUES["injection"])
        for var in got:
            assert var["targeted"] and var["attacker_target"] == target != case["truth"]
            added = adapter.get_path(var["state"], pol["untrusted_field"])[
                len(adapter.get_path(case["state"], pol["untrusted_field"])):]
            assert f'"{target}"' in added or f"result={target}" in added \
                or pol["attack"]["target_phrase"] in added


def test_padding_carries_no_instruction_and_respects_the_policy_list():
    cues = ("ignore", "answer", "classif", "approve", "allow", "block", "instruction", "must")
    for text in ("\n".join(variants.LOG_LINES), variants.UNRELATED_TEXT):
        assert not any(c in text.lower() for c in cues)
    assert len(variants.LOG_LINES) == 6
    for case in CASES:
        pol = POLICIES[case["policy"]]
        got = {v["technique"] for v in variants.generate(case, pol, SEED, "all")
               if v["axis"] == "padding"}
        assert got == set(pol["padding"])
    assert "log_lines" not in POLICIES["data_sensitivity"]["padding"]


def test_option_variants_keep_the_option_set_and_map_back_to_canonical_labels():
    for case, pol, var in all_variants():
        if var["changed"] != "options":
            continue
        base = pol["question"]["options"]
        opts = var["question"]["options"]
        canon = [var["label_map"][o["label"]] for o in opts]
        assert sorted(canon) == sorted(o["label"] for o in base)
        assert var["question"]["type"] == pol["question"]["type"] == "choice" \
            or var["axis"] == "paraphrase"
        if var["axis"] == "option_order":
            assert canon != [o["label"] for o in base], "order must actually change"
            assert {o["label"]: o["criteria"] for o in opts} == \
                {o["label"]: o["criteria"] for o in base}
            assert var["question"]["instructions"] == pol["question"]["instructions"]
        elif var["axis"] == "option_rename":
            rename = pol["misleading_rename"]
            assert case["truth"] != rename["from"]
            assert rename["to"] in [o["label"] for o in opts]
            assert rename["from"] not in [o["label"] for o in opts]
            assert var["label_map"][rename["to"]] == rename["from"] == var["attacker_target"]
            # Only the name changed: every criterion is still attached to the same option.
            assert [o["criteria"] for o in opts] == [o["criteria"] for o in base]
        elif var["axis"] == "paraphrase":
            assert canon == [o["label"] for o in base]
            assert var["question"]["instructions"] != pol["question"]["instructions"]
            assert all(a["criteria"] != b["criteria"] for a, b in zip(opts, base))


def test_axes_that_need_labelled_options_skip_yes_no_and_score_questions():
    for case in CASES:
        pol = POLICIES[case["policy"]]
        axes = {v["axis"] for v in variants.generate(case, pol, SEED, "all")}
        if pol["question"]["type"] != "choice":
            assert "option_order" not in axes and "option_rename" not in axes
        else:
            assert "option_order" in axes
        assert {"padding", "paraphrase", "encoding", "structure"} <= axes
    two = [v["technique"] for v in variants.generate(CASES[0], POLICIES["tool_gate"], SEED, "all")
           if v["axis"] == "option_order"]
    assert two == ["reverse"]            # rotating two options is the same as reversing them


def test_a_technique_that_does_not_apply_raises_instead_of_returning_a_wrong_label():
    allow_case = next(c for c in CASES if c["policy"] == "tool_gate" and c["truth"] == "allow")
    with pytest.raises(ValueError):
        variants.make_variant(allow_case, POLICIES["tool_gate"], "injection", "direct_command",
                              SEED)
    noul_case = next(c for c in CASES if c["policy"] == "injection_screen")
    with pytest.raises(ValueError):
        variants.make_variant(noul_case, POLICIES["injection_screen"], "option_order", "reverse",
                              SEED)
    with pytest.raises(ValueError):
        variants.generate(noul_case, POLICIES["injection_screen"], SEED, "all", ("typo",))


def test_every_variant_is_a_sendable_canonical_case_on_every_wire_format():
    for case, pol, var in all_variants(mode="one"):
        wire_case = variants.to_case(var, pol)
        for fmt in adapter.WIRE_FORMATS:
            req = adapter.build_request(fmt, wire_case, "m")
            json.dumps(req)
        assert adapter.estimate_tokens(wire_case) > 20
