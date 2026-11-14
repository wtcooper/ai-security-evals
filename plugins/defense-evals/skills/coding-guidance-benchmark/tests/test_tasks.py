"""Task selection: the same seed draws the same tasks, for every arm."""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import tasks  # noqa: E402

SKILL = Path(__file__).resolve().parents[1]


def test_baxbench_is_28_scenarios_by_14_frameworks():
    pool = tasks.baxbench_tasks()
    assert len(pool) == 28 * 14 == 392
    assert len({t["id"] for t in pool}) == 392


def test_draw_is_deterministic_and_independent_of_listing_order():
    pool = tasks.baxbench_tasks()
    first = [t["id"] for t in tasks.select(pool, 25, seed=7)]
    shuffled = pool[:]
    random.Random(1).shuffle(shuffled)
    assert [t["id"] for t in tasks.select(shuffled, 25, seed=7)] == first
    assert [t["id"] for t in tasks.select(pool, 25, seed=8)] != first


def test_a_deeper_run_contains_the_shallower_one():
    pool = tasks.baxbench_tasks()
    smoke = [t["id"] for t in tasks.select(pool, 25, seed=7)]
    standard = [t["id"] for t in tasks.select(pool, 100, seed=7)]
    assert standard[:25] == smoke
    assert len(tasks.select(pool, None, seed=7)) == 392


def test_draw_is_not_the_first_n_of_a_sorted_list():
    pool = tasks.baxbench_tasks()
    drawn = tasks.select(pool, 25, seed=7)
    assert len({t["scenario"] for t in drawn}) > 5 and len({t["framework"] for t in drawn}) > 5


def test_framework_restriction_and_unknown_framework():
    pool = tasks.baxbench_tasks(["python-flask", "Go-net/http"])
    assert len(pool) == 56 and {t["framework"] for t in pool} == {"Python-Flask", "Go-net/http"}
    with pytest.raises(ValueError, match="unknown framework"):
        tasks.baxbench_tasks(["Python-Bottle"])


def test_task_id_round_trips_a_framework_with_a_slash():
    tid = tasks.task_id("Calculator", "Go-net/http")
    assert tasks.split_id(tid) == ("Calculator", "Go-net/http")


def test_fake_task_file_is_labelled_fake_and_holds_no_baxbench_scenario():
    header, fake = tasks.load_task_file(SKILL / "fixtures" / "fake_tasks.json")
    assert header["source"] == "fake" and len(fake) == 8
    assert not {t["scenario"] for t in fake} & set(tasks.BAXBENCH_SCENARIOS)
    assert not {t["framework"] for t in fake} & set(tasks.BAXBENCH_FRAMEWORKS)
