import sys, pathlib, codecs

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import m2s_strategies as ms


def _all():
    return list(ms.generate())


def test_covers_all_three_attack_domains():
    domains = {domain for _, domain, *_ in _all()}
    assert domains == {"harmful", "injection", "data_leakage"}


def test_every_case_is_multiturn_strings():
    for cid, domain, strat, goal, turns, cite in _all():
        assert len(turns) >= 2, cid
        assert all(isinstance(t, str) and t.strip() for t in turns), cid
        assert cite  # every strategy is cited


def test_strategy_diversity():
    strats = {strat for _, _, strat, *_ in _all()}
    # the named multi-turn techniques from the research are all represented
    assert {"crescendo", "actor", "puzzler", "decomposition", "payload_split",
            "hypothetical", "cipher", "sycophancy_leak", "trust_override",
            "injection_smuggle"} <= strats


def test_payload_split_reassembles_goal():
    for cid, domain, strat, goal, turns, cite in _all():
        if strat != "payload_split":
            continue
        frags = [t.split('"')[1] for t in turns if t.startswith("Let ")]
        assert "".join(frags) == goal, cid


def test_cipher_decodes_to_goal():
    for cid, domain, strat, goal, turns, cite in _all():
        if strat != "cipher":
            continue
        enc_turn = next(t for t in turns if "Decode this" in t)
        enc = enc_turn.split(": ", 1)[1]
        assert codecs.decode(enc, "rot_13") == goal, cid


def test_data_leakage_has_dedicated_strategies():
    dl = {strat for _, domain, strat, *_ in _all() if domain == "data_leakage"}
    assert {"sycophancy_leak", "trust_override"} <= dl
