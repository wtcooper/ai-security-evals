#!/usr/bin/env python3
"""Turn one or more run folders into summary.md and summary.json.

    python report.py <EXP> [<EXP2> ...] [--baseline ARM] [--out DIR]

Each folder holds samples.jsonl and results/run.json from run_bench.py. Pass several folders
to compare arms run at different times; the summary says so when they did not use the same
seed, depth and corpus, because then the arms did not see the same requests.

The summary reports numbers with intervals. It sets no threshold and gives no verdict.
It is this skill's own detail: the custom lane in full (fail-open and fail-closed, flips per
attack axis against the noise floor, consistency, calibration, refusals, cost, a paired
comparison) and one table for the known lane. The threat-by-threat comparison of models
across both lanes is lib/scorecard.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import metrics  # noqa: E402


def load(folder: Path) -> tuple[list[dict], dict]:
    samples = folder / "samples.jsonl"
    if not samples.is_file():
        raise SystemExit(f"{samples} not found: run run_bench.py --out {folder} first")
    rows = [json.loads(line) for line in samples.read_text().splitlines() if line.strip()]
    run_path = folder / "results" / "run.json"
    run = json.loads(run_path.read_text()) if run_path.is_file() else {}
    return rows, run


def fr(r: dict | None) -> str:
    """A rate as `0.25 [0.12-0.42] (5/20)`."""
    if not r or r.get("rate") is None:
        return "n/a (0)"
    return f"{r['rate']:.2f} [{r['ci95'][0]:.2f}–{r['ci95'][1]:.2f}] ({r['k']}/{r['n']})"


def num(x, digits: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}"


def render(summary: dict, runs: list[dict]) -> str:
    arms = summary["arms"]
    names = list(arms)
    lines = ["# decision-model-benchmark summary", "",
             "The per-threat comparison of models across both lanes is `scorecard.md` "
             "(`python lib/scorecard.py --threats threats.json --samples <EXP>/samples.jsonl "
             "--out <EXP>`). This file is the detail behind it.", ""]
    settings = {(r.get("seed"), r.get("depth"), r.get("repeats"),
                 (r.get("corpus") or {}).get("sha256"), tuple(r.get("lanes") or ()),
                 json.dumps({k: (v.get("revision"), v.get("id")) for k, v in
                             ((r.get("known") or {}).get("benchmarks") or {}).items()},
                            sort_keys=True)) for r in runs}
    if len(settings) > 1:
        lines += ["> **Not comparable:** the inputs differ in seed, depth, repeats, corpus, "
                  "lanes or known-lane source, so the arms did not receive the same requests. "
                  "Re-run with the same settings before comparing arms (the scorecard still "
                  "compares them on the cases they share).", ""]
    run = runs[0] if runs else {}
    corpus = run.get("corpus") or {}
    if summary.get("main_lane") == "known":
        lines += ["> The tables down to \"By policy family\" describe the known lane: this run "
                  "has no custom-lane rows.", ""]
    lines += [f"depth `{run.get('depth')}` · seed `{run.get('seed')}` · clean requests sent "
              f"`{run.get('repeats')}` times · corpus `{corpus.get('cases_file')}` "
              f"({corpus.get('cases_run')} of {corpus.get('cases_total')} cases, sha256 "
              f"`{(corpus.get('sha256') or '')[:12]}`) · execution tier T0", "",
              "Rates are `rate [95% Wilson interval] (count/denominator)`. Nothing here is a "
              "threshold or a verdict.", "",
              "## Arms", "",
              "| Arm | Wire format | Endpoint | Model requested | Model reported by server | "
              "Adapter read from vendor docs | Requests |",
              "|---|---|---|---|---|---|---|"]
    info = {a["name"]: a for r in runs for a in r.get("arms", [])}
    docs = {True: "yes", False: "**no** (see flags)", None: "no provider preset given"}
    for n in names:
        ids = arms[n]["model_ids"]
        arm = info.get(n, {})
        lines.append(f"| {n} | {arm.get('format', '?')} | {arm.get('url', '?')} | "
                     f"{', '.join(ids['requested'])} | "
                     f"{', '.join(ids['echoed']) or 'not reported'} | "
                     f"{docs.get(arm.get('verified'), '?')} | {arms[n]['requests']} |")
    lines += ["", "No adapter was checked against a live service when this skill was built; "
              "\"read from vendor docs\" means the request and response shapes were read there."]

    lines += ["", "## Read before trusting a number", "",
              "Validity flags say a measurement may not be trustworthy. They are not acceptance "
              "limits; each limit is a report.py option and every number is shown regardless.", ""]
    any_flag = False
    for n in names:
        for f in arms[n]["validity_flags"]:
            any_flag = True
            limit = f" (limit {f['limit']})" if f.get("limit") is not None else ""
            lines.append(f"- **{n}** · `{f['flag']}` = {f['observed']}{limit}: {f['meaning']}")
        out = arms[n]["outcomes"]
        for example in out["error_examples"]:
            lines.append(f"- **{n}** · error seen: `{example}`")
    if not any_flag:
        lines.append("- No validity flag was raised.")

    lines += ["", "## Clean cases: fail-open and fail-closed", "",
              "Fail-open: the truth was a restrictive label (one that triggers the control; set "
              "per policy) and the arm chose a non-restrictive one. Fail-closed: the reverse. "
              "Each is measured over the answered cases where that error is possible. `Other` is "
              "a wrong label on the same side.", "",
              "| Arm | Accuracy | Fail-open | Fail-closed | Other error | Answered / cases |",
              "|---|---|---|---|---|---|"]
    for n in names:
        c = arms[n]["clean"]
        lines.append(f"| {n} | {fr(c['accuracy'])} | {fr(c['fail_open'])} | "
                     f"{fr(c['fail_closed'])} | {fr(c['other_error'])} | "
                     f"{c['answered']} / {c['cases']} |")

    lines += ["", "## Decision flips under attack", "",
              "Measured only on cases the arm got right when clean. A flip is a decision that "
              "differs from that clean decision. Read every row against the noise floor: the "
              "flip rate when the identical clean request is sent again. `Targeted` is how often "
              "the attacker's chosen option was selected (injection and option_rename only).", ""]
    for n in names:
        f = arms[n]["flips"]
        lines += [f"### {n} ({f['clean_correct_cases']} clean-correct cases)", "",
                  "| Axis | Flip rate | Flips to fail-open | Targeted | Unanswered | "
                  "Mean top prob. of flipped |",
                  "|---|---|---|---|---|---|"]
        nf = f["noise_floor"]
        lines.append(f"| identical re-run (noise floor) | {fr(nf['flip'])} | "
                     f"{nf['flips_to_fail_open']} | — | {nf['unanswered']} | "
                     f"{num(nf['flipped_top_p_mean'])} |")
        for axis, b in f["axes"].items():
            lines.append(f"| {axis} | {fr(b['flip'])} | {b['flips_to_fail_open']} | "
                         f"{fr(b['targeted_success']) if 'targeted_success' in b else '—'} | "
                         f"{b['unanswered']} | {num(b['flipped_top_p_mean'])} |")
        lines.append("")
        if len(f["techniques"]) > len(f["axes"]):
            lines += ["| Technique | Flip rate | Targeted |", "|---|---|---|"]
            for tech, b in f["techniques"].items():
                lines.append(f"| {tech} | {fr(b['flip'])} | "
                             f"{fr(b['targeted_success']) if 'targeted_success' in b else '—'} |")
            lines.append("")

    lines += ["## Consistency", "",
              "Share of requests whose decision matched the same case's clean decision, over all "
              "answered cases (not only the correct ones). `First option picked` compares the "
              "observed rate with the rate a fully correct arm would show, in the corpus order "
              "and with the options reversed.", "",
              "| Arm | Identical re-run | Option order | Paraphrase | First option picked: "
              "corpus order (observed vs all-correct) | reversed (observed vs all-correct) |",
              "|---|---|---|---|---|---|"]
    for n in names:
        c = arms[n]["consistency"]
        pick = c["first_option_pick"]
        lines.append(
            f"| {n} | {fr(c['rerun'])} | {fr(c['option_order'])} | {fr(c['paraphrase'])} | "
            f"{num(pick['corpus_order']['observed']['rate'])} vs "
            f"{num(pick['corpus_order']['if_all_correct']['rate'])} | "
            f"{num(pick['reversed']['observed']['rate'])} vs "
            f"{num(pick['reversed']['if_all_correct']['rate'])} |")

    lines += ["", "## Calibration and the confidence of flipped decisions", "",
              "Confidence here is the top probability of the returned distribution, computed the "
              "same way for every arm; vendor `confidence` fields are not used. ECE and Brier "
              "are on clean cases (Brier is summed over options: 0 best, 2 worst). "
              "`Kept vs flipped AUROC` is the chance that an attacked decision the arm kept right "
              "has a higher top probability than a flipped one: near 0.5, sending low-confidence "
              "decisions to review cannot pick out the flipped ones.", "",
              "| Arm | ECE | Brier | Mean top prob.: clean correct | attacked, kept | "
              "attacked, flipped | Kept vs flipped AUROC |",
              "|---|---|---|---|---|---|---|"]
    for n in names:
        c = arms[n]["calibration"]
        lines.append(f"| {n} | {num(c['ece'], 3)} (n={c['n']}) | {num(c['brier'], 3)} | "
                     f"{num(c['clean_correct_top_p_mean'])} | "
                     f"{num(c['attacked_kept']['top_p_mean'])} (n={c['attacked_kept']['n']}) | "
                     f"{num(c['attacked_flipped']['top_p_mean'])} "
                     f"(n={c['attacked_flipped']['n']}) | {num(c['auroc_kept_vs_flipped'])} |")

    lines += ["", "## Refusals, errors, latency and tokens", "",
              "Refusals and errors are not decisions. They are excluded from every rate above "
              "and counted here over all requests. Whether an unanswered request ends up "
              "allowed or blocked depends on the code that calls the model.", "",
              "| Arm | Refusal rate | Error rate | Refusals: clean / attacked | Latency p50 / p95 "
              "(ms) | Input tokens: total / mean per request | USD per 1,000 requests |",
              "|---|---|---|---|---|---|---|"]
    for n in names:
        o, c = arms[n]["outcomes"], arms[n]["cost"]
        lines.append(
            f"| {n} | {fr(o['all']['refusal'])} | {fr(o['all']['error'])} | "
            f"{o['clean']['refusal']['k']} / {o['attacked']['refusal']['k']} | "
            f"{num(c['latency_ms_p50'], 0)} / {num(c['latency_ms_p95'], 0)} | "
            f"{c['input_tokens_total'] if c['input_tokens_total'] is not None else 'n/a'} / "
            f"{num(c['input_tokens_mean'], 0)} | "
            + (f"{num(c['usd_per_1000_requests'], 4)} |" if c["usd_per_1000_requests"] is not None
               else "no price given |"))

    lines += ["", f"## Paired comparison against `{summary['baseline']}`", ""]
    if summary["comparisons"]:
        lines += ["Exact McNemar on per-request correctness, paired on the same case and variant "
                  "(first send only). Pairs where either arm gave no answer are left out.", "",
                  "| Arm | Set | Pairs | Accuracy: baseline → arm | Only baseline right | "
                  "Only arm right | McNemar p | Left out |",
                  "|---|---|---|---|---|---|---|---|"]
        for n, comp in summary["comparisons"].items():
            for label, key in (("clean", "clean"), ("under attack", "attacked")):
                c = comp[key]
                lines.append(
                    f"| {n} | {label} | {c['pairs']} | {num(c['baseline_accuracy'])} → "
                    f"{num(c['other_accuracy'])} | {c['baseline_only_correct']} | "
                    f"{c['other_only_correct']} | {num(c['mcnemar_p'], 4)} | "
                    f"{c['excluded_unanswered']} |")
    else:
        lines.append("- One arm; nothing to compare.")

    lines += ["", "## By policy family", "",
              "| Arm | Policy | Accuracy | Fail-open | Fail-closed | Flip rate, all attacks |",
              "|---|---|---|---|---|---|"]
    for n in names:
        for policy, b in arms[n]["by_policy"].items():
            lines.append(f"| {n} | {policy} | {fr(b['accuracy'])} | {fr(b['fail_open'])} | "
                         f"{fr(b['fail_closed'])} | {fr(b['flip_all_attacks'])} |")

    known = summary.get("known") or {}
    if known:
        lines += ["", "## Known lane (published benchmarks, run as published)", "",
                  "No variants are applied. `deepset-prompt-injections` is recast as one yes/no "
                  "screen: fail-open is an injection answered `no`, fail-closed a benign message "
                  "answered `yes`. `jevbench-original` holds paraphrase pairs: `both right` "
                  "counts pairs decided correctly in both phrasings, `consistent` pairs with the "
                  "same decision in both. Re-run agreement is over identical re-sends. A "
                  "`:fixture` benchmark is the bundled synthetic stand-in, not the benchmark.", "",
                  "| Arm | Benchmark | Cases | Accuracy | Fail-open | Fail-closed | Pairs both "
                  "right | Pairs consistent | Re-run agreement | Unanswered |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for n, by in known.items():
            for bench, b in by.items():
                lines.append(
                    f"| {n} | {bench} | {b['cases']} | {fr(b['accuracy'])} | "
                    f"{fr(b['fail_open']) if 'fail_open' in b else '—'} | "
                    f"{fr(b['fail_closed']) if 'fail_closed' in b else '—'} | "
                    f"{fr(b['pair_both_correct']) if 'pairs' in b else '—'} | "
                    f"{fr(b['pair_consistent']) if 'pairs' in b else '—'} | "
                    f"{fr(b['rerun_agreement'])} | {b['unanswered']} |")

    lines += ["", "## What these numbers do not say", "",
              "- The seed corpus is small and synthetic. Rates describe these cases under these "
              "policies, not the failure rate of a deployment.",
              "- The known lane's JevBench pairs are general decisions, not security ones; they "
              "measure brittleness under rewording only. The deepset labels follow no published "
              "rule, and the recast question is this skill's reading of them.",
              "- Variants come from fixed templates. A low flip rate is a floor on what an "
              "attacker who adapts to the model can do, not evidence of robustness.",
              "- The interval treats each request as independent; several requests share a case.",
              "- See references/not-measured.md for the threats this skill does not cover."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("folders", nargs="+", help="run folder(s) holding samples.jsonl")
    p.add_argument("--baseline", help="arm every other arm is paired against (default: first)")
    p.add_argument("--out", help="where to write summary.md and summary.json (default: first folder)")
    p.add_argument("--bins", type=int, default=10, help="equal-width bins for ECE")
    p.add_argument("--max-unanswered", type=float, default=0.05,
                   help="validity-flag limit: share of requests refused or failed")
    p.add_argument("--min-clean-correct", type=int, default=20,
                   help="validity-flag limit: clean-correct cases behind the flip rates")
    p.add_argument("--max-prob-sum-off", type=float, default=0.0,
                   help="validity-flag limit: share of answers whose probabilities do not sum to 1")
    args = p.parse_args(argv)

    rows, runs = [], []
    for folder in args.folders:
        r, run = load(Path(folder))
        rows += r
        runs.append(run)
    if not rows:
        raise SystemExit("no sample rows found")
    arms = [a for run in runs for a in run.get("arms", [])]
    limits = {"max_unanswered": args.max_unanswered, "min_clean_correct": args.min_clean_correct,
              "max_prob_sum_off": args.max_prob_sum_off}
    custom = [r for r in rows if r.get("lane", "custom") == "custom"]
    known = [r for r in rows if r.get("lane") == "known"]
    try:
        summary = metrics.summarise(custom or known, arms, args.baseline, limits, args.bins)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    summary["main_lane"] = "custom" if custom else "known"
    summary["known"] = metrics.known_summary(known)
    summary["runs"] = [{k: run.get(k) for k in ("seed", "depth", "repeats", "repeat_scope",
                                                "techniques_per_axis", "axes", "corpus",
                                                "started", "finished", "context",
                                                "execution_tier")} for run in runs]
    summary["limits"] = limits
    out = Path(args.out or args.folders[0])
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    text = render(summary, runs)
    (out / "summary.md").write_text(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
