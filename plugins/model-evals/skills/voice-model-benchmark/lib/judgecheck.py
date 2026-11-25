#!/usr/bin/env python3
"""Second-judge check: does a result depend on who graded it?

    python judgecheck.py --primary <EXP>/samples.jsonl --secondary <EXP>/samples_regrade.jsonl \
        --out <EXP> [--group target|threat]

Both files hold samples rows for the SAME cases: the first graded by the run's judge, the
second re-graded by a different judge model or a reworded rubric (each skill documents how to
produce it). Rows are paired on arm, the thing measured, the case and the repeat.

Written to judge_check.md / judge_check.json:
  * agreement and Cohen's kappa between the two judges, overall and per benchmark or threat
    (kappa discounts the agreement two raters would reach by chance)
  * each arm's good rate under each judge, and whether the order of arms or the leader changes
  * length sensitivity: the correlation between a good verdict and the reply's length, under
    each judge. Some correlation is expected (refusals tend to be short); a judge whose
    correlation differs clearly from the other's is reacting to length, not only to content

Nothing here is a threshold. If the order of arms changes when the judge does, the result
measures the judge as much as the arms: revisit the rubric before reading it as a difference.
Human labelling is not part of this check.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path


def load(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def _group(row: dict, by: str) -> str:
    if by == "threat" and row.get("threat"):
        return f"{row['threat']} ({row.get('lane', '')})"
    return str(row.get("target") or row.get("benchmark") or "")


def _key(row: dict, by: str) -> tuple:
    return (row.get("arm"), _group(row, by), str(row.get("case", row.get("sample"))),
            str(row.get("repeat", row.get("epoch", 1))))


def cohen_kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    """Cohen's kappa for two raters on a binary verdict; None when undefined."""
    n = len(pairs)
    if not n:
        return None
    agree = sum(1 for a, b in pairs if a == b) / n
    pa = sum(1 for a, _ in pairs if a) / n
    pb = sum(1 for _, b in pairs if b) / n
    chance = pa * pb + (1 - pa) * (1 - pb)
    if chance >= 1.0:
        return None
    return round((agree - chance) / (1 - chance), 4)


def point_biserial(rows: list[dict]) -> tuple[float | None, int]:
    """Pearson correlation between a good verdict (1/0) and reply length."""
    xs = [(1.0 if r["good"] else 0.0, float(r["response_chars"])) for r in rows
          if r.get("good") is not None and isinstance(r.get("response_chars"), (int, float))]
    n = len(xs)
    if n < 3:
        return None, n
    mx = sum(x for x, _ in xs) / n
    my = sum(y for _, y in xs) / n
    sxy = sum((x - mx) * (y - my) for x, y in xs)
    sx = math.sqrt(sum((x - mx) ** 2 for x, _ in xs))
    sy = math.sqrt(sum((y - my) ** 2 for _, y in xs))
    if not sx or not sy:
        return None, n
    return round(sxy / (sx * sy), 4), n


def _order(rates: dict[str, float]) -> list[str]:
    return sorted(rates, key=lambda a: (-rates[a], a))


def check(primary: list[dict], secondary: list[dict], by: str = "target") -> dict:
    p = {_key(r, by): r for r in primary}
    s = {_key(r, by): r for r in secondary}
    shared = [k for k in p if k in s and p[k].get("good") is not None
              and s[k].get("good") is not None]
    judges = {"primary": sorted({str(r.get("judge")) for r in primary if r.get("judge")}),
              "secondary": sorted({str(r.get("judge")) for r in secondary if r.get("judge")})}
    groups: dict = defaultdict(list)
    for k in shared:
        groups[k[1]].append(k)
    out_groups = {}
    for g, keys in sorted(groups.items()):
        pairs = [(bool(p[k]["good"]), bool(s[k]["good"])) for k in keys]
        arms = sorted({k[0] for k in keys})
        rates = {}
        for a in arms:
            ak = [k for k in keys if k[0] == a]
            rates[a] = {"n": len(ak),
                        "primary": round(sum(bool(p[k]["good"]) for k in ak) / len(ak), 4),
                        "secondary": round(sum(bool(s[k]["good"]) for k in ak) / len(ak), 4)}
        po = _order({a: r["primary"] for a, r in rates.items()})
        so = _order({a: r["secondary"] for a, r in rates.items()})
        top_p = {a for a in arms if rates[a]["primary"] == rates[po[0]]["primary"]}
        top_s = {a for a in arms if rates[a]["secondary"] == rates[so[0]]["secondary"]}
        out_groups[g] = {
            "n": len(pairs), "agreement": round(sum(a == b for a, b in pairs) / len(pairs), 4),
            "kappa": cohen_kappa(pairs),
            "primary_only_good": sum(1 for a, b in pairs if a and not b),
            "secondary_only_good": sum(1 for a, b in pairs if b and not a),
            "rates": rates, "order_primary": po, "order_secondary": so,
            "order_changes": len(arms) > 1 and po != so,
            "leader_changes": len(arms) > 1 and not (top_p & top_s)}
    all_pairs = [(bool(p[k]["good"]), bool(s[k]["good"])) for k in shared]
    length = {}
    for name, rows in (("primary", primary), ("secondary", secondary)):
        r, n = point_biserial(rows)
        length[name] = {"r": r, "n": n}
    return {"judges": judges, "paired_cases": len(shared),
            "unpaired_primary": len([k for k in p if k not in s]),
            "agreement": round(sum(a == b for a, b in all_pairs) / len(all_pairs), 4)
            if all_pairs else None,
            "kappa": cohen_kappa(all_pairs), "groups": out_groups, "length": length}


def render(res: dict) -> str:
    j = res["judges"]
    L = ["# Second-judge check", "",
         f"Primary judge: `{', '.join(j['primary']) or 'unrecorded'}`. Second judge: "
         f"`{', '.join(j['secondary']) or 'unrecorded'}`. {res['paired_cases']} case(s) graded "
         "by both. This check says whether results depend on the judge; it does not say "
         "which judge is right, and no human labels were used.", ""]
    if res["paired_cases"] == 0:
        return "\n".join(L + ["No case was graded by both judges."]) + "\n"
    L += [f"Overall agreement {res['agreement']:.0%}, Cohen's kappa "
          f"{res['kappa'] if res['kappa'] is not None else 'undefined'}.", ""]
    changed = [g for g, v in res["groups"].items() if v["order_changes"]]
    L += ["## Read first", ""]
    L += ([f"- `{g}`: the order of arms changes under the second judge"
           + (" and so does the leader" if res["groups"][g]["leader_changes"] else "")
           + ". Revisit the rubric before reading this row as a difference between arms."
           for g in changed] or ["- The order of arms is the same under both judges on every row."])
    L += ["", "## By benchmark or threat", "",
          "| Row | Cases | Agreement | Kappa | Good only under primary / only under second | Order (primary → second) |",
          "|---|---|---|---|---|---|"]
    for g, v in res["groups"].items():
        L.append(f"| `{g}` | {v['n']} | {v['agreement']:.0%} | "
                 f"{v['kappa'] if v['kappa'] is not None else '—'} | "
                 f"{v['primary_only_good']} / {v['secondary_only_good']} | "
                 f"{' > '.join(v['order_primary'])} → {' > '.join(v['order_secondary'])} |")
    L += ["", "## Good rate by arm under each judge", "",
          "| Row | Arm | Cases | Primary | Second |", "|---|---|---|---|---|"]
    for g, v in res["groups"].items():
        for a, r in v["rates"].items():
            L.append(f"| `{g}` | {a} | {r['n']} | {r['primary']:.2f} | {r['secondary']:.2f} |")
    ln = res["length"]
    L += ["", "## Length sensitivity", "",
          "Correlation between a good verdict and the reply's length (point-biserial). Some "
          "correlation is expected, because refusals tend to be short; compare the two judges "
          "rather than reading either number alone.", "",
          "| Judge | r | Rows with a length |", "|---|---|---|",
          f"| primary | {ln['primary']['r'] if ln['primary']['r'] is not None else '—'} | {ln['primary']['n']} |",
          f"| second | {ln['secondary']['r'] if ln['secondary']['r'] is not None else '—'} | {ln['secondary']['n']} |"]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--primary", required=True)
    ap.add_argument("--secondary", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--group", choices=("target", "threat"), default="target")
    a = ap.parse_args(argv)
    res = check(load(a.primary), load(a.secondary), a.group)
    if res["judges"]["primary"] and res["judges"]["primary"] == res["judges"]["secondary"]:
        print("both files were graded by the same judge; nothing to compare", file=sys.stderr)
        return 2
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "judge_check.json").write_text(json.dumps(res, indent=2))
    (out / "judge_check.md").write_text(render(res))
    print(out / "judge_check.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
