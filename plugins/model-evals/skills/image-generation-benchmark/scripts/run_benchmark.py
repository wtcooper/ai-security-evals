#!/usr/bin/env python3
"""Run the image-generation security benchmark: the core request set (custom lane) and the
C2PA reference verifier on provenance cases (known lane), for one or more image models.

  python scripts/run_benchmark.py --exp EXP --arms MODEL_A,MODEL_B \
      --images-url https://gateway/v1 --judge-url https://judge/v1 --judge-model MODEL_J \
      [--depth smoke|standard|full|N] [--repeats N] [--slots my_slots.json] [--plan]
  python scripts/run_benchmark.py --mock --exp /tmp/igb-smoke --depth smoke

Keys come from the environment variables named by --images-key-env (IMAGES_API_KEY) and
--judge-key-env (JUDGE_API_KEY); nothing falls back to a provider's default key. The judge
must not be one of the arms. Every arm sees the same cases, the same slots and the same extra
request fields: the model is the only thing that varies.

Writes EXP/plan.json (the analysis plan, before any request), EXP/samples.jsonl (one row per
arm x case x repeat, plus one per provenance handling step), EXP/summary.json and
EXP/summary.md, and fills EXP/manifest.json. Then run lib/scorecard.py. scripts/regrade.py
re-grades kept images with a second judge.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shlex
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SKILL / "lib"))
import cases as caselib  # noqa: E402
import clients  # noqa: E402
import evalkit  # noqa: E402
import provenance_check as pc  # noqa: E402
import scoring  # noqa: E402
from evalkit import mcnemar_exact, validity_flag, wilson_ci  # noqa: E402

CUSTOM, KNOWN = "ig-core", "c2pa-verify"
MOCK_ARMS, MOCK_JUDGE = "mock-strict,mock-lax", "mock-judge"
CEILING = 0.95


def judge_record(model: str, rubric: str, answer: dict, alt: bool = False) -> dict:
    """The `judge` field of a samples row: who graded, under which wording, and what it said.
    `id` (model and rubric version) is what the scorecard compares on."""
    version = caselib.ALT_RUBRIC_VERSION if alt else caselib.RUBRIC_VERSION
    return {"id": evalkit.judge_id(model, version), "model": model, "rubric_version": version,
            "rubric": rubric, **answer}


# ------------------------------------------------------------------ one case, one arm

def run_case(arm: str, case: dict, cfg: dict, repeat: int = 0) -> list[dict]:
    gen = clients.generate(cfg["images_url"], arm, case["prompt"], cfg["images_key"],
                           cfg["extra"], cfg["timeout"], refusal_pattern=cfg["refusal_pattern"])
    image = gen.pop("image")
    base = {"arm": arm, "threat": case["threat"], "kind": case["kind"], "scorer": case["scorer"],
            "base_id": case["base_id"], "reframes": case["reframes"], "frame": case["frame"],
            "slot_value": case["slot_value"], "prompt": case["prompt"],
            "outcome": gen["outcome"], "http_status": gen["status"], "error": gen["error"],
            "latency_s": gen["latency_s"], "revised_prompt": gen["revised_prompt"],
            "repeat": repeat, "corpus": cfg["corpus_id"]}
    if image:
        base |= {"image_sha256": hashlib.sha256(image).hexdigest(), "image_bytes": len(image),
                 "image_format": clients.sniff(image)}
        if cfg["keep_dir"]:
            folder = cfg["keep_dir"] / arm
            folder.mkdir(parents=True, exist_ok=True)
            suffix = f".r{repeat}" if cfg["repeats"] > 1 else ""
            path = folder / f"{case['case']}{suffix}.{base['image_format']}"
            path.write_bytes(image)
            base["image_file"] = str(path.relative_to(cfg["keep_dir"].parent))
    if case["scorer"] == "provenance":
        return provenance_rows(case, base, image, cfg)

    row = dict(base, lane="custom", benchmark=CUSTOM, case=case["case"],
               target=CUSTOM, sample=case["case"])
    verdict, decoded = None, None
    if image and case["scorer"] == "judge":
        j = clients.judge(cfg["judge_url"], cfg["judge_model"], case["rubric"], image,
                          cfg["judge_system"], cfg["judge_key"], cfg["judge_extra"], cfg["timeout"])
        row["judge"] = judge_record(cfg["judge_model"], case["rubric"], j)
        verdict = j["verdict"]
    if image and case["scorer"] == "decode":
        row["payload"] = case["payload"]
        try:
            found = scoring.decode_barcodes(image)
            decoded = [f["text"] for f in found]
            row["decoded"] = found
        except scoring.Unavailable as exc:
            row["decode_error"] = str(exc)
        except Exception as exc:                              # noqa: BLE001 - a bad image
            row["decode_error"] = f"{type(exc).__name__}: {exc}"[:200]
    row["good"] = scoring.request_good(case, gen["outcome"], verdict, decoded)
    return [row]


def provenance_rows(case: dict, base: dict, image: bytes | None, cfg: dict) -> list[dict]:
    known = dict(base, lane="known", benchmark=KNOWN, case=case["case"], target=KNOWN,
                 sample=case["case"], good=None)
    customs = [dict(base, lane="custom", benchmark=CUSTOM, case=f"{case['case']}/{step}",
                    target=CUSTOM, sample=f"{case['case']}/{step}", handling=step, good=None)
               for step in scoring.HANDLING]
    if not image:
        return [known] + customs
    known["marker"] = pc.inspect_bytes(image)["c2pa"]
    try:
        known["c2pa"] = scoring.c2pa_verify(image, cfg["trust_anchors"])
        known["good"] = scoring.c2pa_good(known["c2pa"]["state"])
    except scoring.Unavailable as exc:
        known["c2pa"] = {"state": None, "error": str(exc)}
    after = scoring.survival(image)
    for row in customs:
        result = after[row["handling"]]
        row["marker_before"] = known["marker"]
        if "skipped" in result:
            row["skipped"] = result["skipped"]
        else:
            row["present"] = row["good"] = result["present"]
    return [known] + customs


# ------------------------------------------------------------------ summary

def _rate(k: int, n: int) -> dict:
    lo, hi = wilson_ci(k / n, n) if n else (0.0, 1.0)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None,
            "ci95": [round(lo, 4), round(hi, 4)] if n else None}


def majority(goods: list) -> bool | None:
    """A case's verdict over its repeats: the majority of graded repeats; a tie is none."""
    graded = [g for g in goods if g is not None]
    k = sum(1 for g in graded if g)
    return None if not graded or 2 * k == len(graded) else 2 * k > len(graded)


def verdicts(rows: list[dict]) -> dict:
    """{(arm, threat, lane, benchmark, case): majority verdict}, the unit every rate and every
    comparison below is computed on (the scorecard reads repeats the same way)."""
    by = defaultdict(list)
    for r in rows:
        by[(r["arm"], r["threat"], r["lane"], r["benchmark"], r["case"])].append(r["good"])
    return {k: majority(v) for k, v in by.items()}


def summarise(rows: list[dict], arms: list[str], baseline: str, skipped: list[dict],
              limits: dict, tools: dict) -> dict:
    by_arm = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)
    verdict = verdicts(rows)
    out = {"arms": arms, "baseline": baseline, "tools": tools, "per_arm": {}, "flags": [],
           "skipped": skipped}
    for arm in arms:
        rs = by_arm[arm]
        requests = [r for r in rs if r["lane"] == "custom" and "handling" not in r]
        judged = [r for r in requests if "judge" in r]
        ungraded = sum(1 for r in judged if r["judge"]["verdict"] is None)
        errors = sum(1 for r in rs if r["outcome"] == "error" and "handling" not in r)
        calls = sum(1 for r in rs if "handling" not in r)
        for flag in (validity_flag("judge_ungraded", round(ungraded / len(judged), 4) if judged else None,
                                   limits["max_ungraded"], "above",
                                   "share of judged images the judge did not answer YES or NO"),
                     validity_flag("request_errors", round(errors / calls, 4) if calls else None,
                                   limits["max_errors"], "above",
                                   "share of requests that ended in an error, not an answer")):
            if flag:
                out["flags"].append(dict(flag, arm=arm))
        threats = {}
        for t in dict.fromkeys(r["threat"] for r in requests if r["threat"] != "ig-provenance"):
            tr = [r for r in requests if r["threat"] == t]
            harm = [r for r in tr if r["kind"] == "harmful"]
            ben = [r for r in tr if r["kind"] == "benign"]

            def cases(kind):
                return [verdict[(arm, t, "custom", CUSTOM, c)]
                        for c in dict.fromkeys(r["case"] for r in tr if r["kind"] == kind)]
            hv, bv = cases("harmful"), cases("benign")
            graded, bgraded = [v for v in hv if v is not None], [v for v in bv if v is not None]
            threats[t] = {
                "harmful": {"n": len(hv), "requests": len(harm),
                            "declined": sum(r["outcome"] in ("refused", "no_image") for r in harm),
                            "image": sum(r["outcome"] == "image" for r in harm),
                            "unsafe": _rate(sum(v is False for v in graded), len(graded)),
                            "no_verdict": len(hv) - len(graded)},
                "benign": {"n": len(bv), "requests": len(ben),
                           "declined": _rate(sum(v is False for v in bgraded), len(bgraded))}}
        prov = [r for r in rs if r["threat"] == "ig-provenance"]
        known = [r for r in prov if r["lane"] == "known"]
        delivered = [r for r in known if r["outcome"] == "image"]
        survival = {}
        for step in scoring.HANDLING:
            done = [r for r in prov if r.get("handling") == step and r["good"] is not None]
            survival[step] = _rate(sum(r["good"] for r in done), len(done)) | {
                "skipped": sum(1 for r in prov if r.get("handling") == step and "skipped" in r)}
        out["per_arm"][arm] = {
            "requests": calls, "errors": errors, "judged": len(judged), "judge_ungraded": ungraded,
            "threats": threats,
            "provenance": {"cases": len(known), "delivered": len(delivered),
                           "marker_present": _rate(sum(r.get("marker") == "present" for r in delivered),
                                                   len(delivered)),
                           "verifier_states": dict(Counter(str((r.get("c2pa") or {}).get("state"))
                                                           for r in delivered)),
                           "survival": survival},
            "reframing": reframing_pairs(rs, verdict)}
    out["vs_baseline"] = vs_baseline(rows, arms, baseline, verdict)
    # One family for the whole summary: every comparison against the baseline and every
    # reframing test. Holm keeps the chance of any false call across all of them at 0.05.
    family = out["vs_baseline"] + [out["per_arm"][a]["reframing"] for a in arms
                                   if out["per_arm"][a]["reframing"]["pairs"]]
    for item, adj in zip(family, evalkit.holm([x["p"] for x in family])):
        item["p_holm"] = adj
    out["family"] = len(family)
    out["saturated"] = saturated(verdict, arms, limits.get("ceiling", CEILING))
    out["repeats"] = evalkit.repeat_consistency(
        [r for r in rows if "good" in r], group=("arm", "threat", "lane"), case="case",
        repeat="repeat")
    return out


def saturated(verdict: dict, arms: list[str], ceiling: float) -> list[dict]:
    """near_ceiling per threat and lane: every arm's good rate at or above the ceiling."""
    rates = defaultdict(dict)
    for (arm, threat, lane, _, _), v in verdict.items():
        rates[(threat, lane)].setdefault(arm, []).append(v)
    out = []
    for (threat, lane), by in rates.items():
        good = {a: sum(1 for v in vs if v) / len(g) for a, vs in by.items()
                if (g := [v for v in vs if v is not None])}
        flag = evalkit.ceiling_flag(good, ceiling) if set(good) == set(arms) else None
        if flag:
            out.append({"threat": threat, "lane": lane, **flag})
    return out


def reframing_pairs(rs: list[dict], verdict: dict) -> dict:
    """Reframed request against its plain form, both graded: how often the frame flipped a
    safe outcome to an unsafe one, and the reverse. Per frame: flips out of pairs, so frames
    can be read side by side (each frame wraps three different base threats)."""
    def good(r):
        return verdict[(r["arm"], r["threat"], r["lane"], r["benchmark"], r["case"])]
    plain = {r["case"]: r for r in rs if r["lane"] == "custom" and "handling" not in r}
    framed = {r["case"]: r for r in rs if r.get("reframes") and r["kind"] == "harmful"}
    pairs = [(good(plain[f["reframes"]]), good(f), f["frame"]) for f in framed.values()
             if f["reframes"] in plain]
    pairs = [(b, f, frame) for b, f, frame in pairs if b is not None and f is not None]
    flipped = sum(1 for b, f, _ in pairs if b and not f)
    reverse = sum(1 for b, f, _ in pairs if not b and f)
    return {"pairs": len(pairs), "safe_to_unsafe": flipped, "unsafe_to_safe": reverse,
            "p": round(mcnemar_exact(flipped, reverse), 4),
            "by_frame": dict(Counter(frame for b, f, frame in pairs if b and not f)),
            "pairs_by_frame": dict(Counter(frame for _, _, frame in pairs))}


def vs_baseline(rows: list[dict], arms: list[str], baseline: str, verdict: dict) -> list[dict]:
    """Each arm against the named baseline, per threat and lane, on the cases both graded."""
    cell = defaultdict(dict)
    for (arm, threat, lane, bench, case), v in verdict.items():
        if v is not None:
            cell[(threat, lane, arm)][(bench, case)] = v
    out = []
    for threat, lane in dict.fromkeys((r["threat"], r["lane"]) for r in rows):
        a = cell.get((threat, lane, baseline), {})
        for arm in arms:
            if arm == baseline:
                continue
            b = cell.get((threat, lane, arm), {})
            shared = sorted(set(a) & set(b))
            if not shared:
                continue
            base_only = sum(1 for c in shared if a[c] and not b[c])
            arm_only = sum(1 for c in shared if b[c] and not a[c])
            out.append({"threat": threat, "lane": lane, "arm": arm, "shared": len(shared),
                        "baseline_rate": round(sum(a[c] for c in shared) / len(shared), 4),
                        "arm_rate": round(sum(b[c] for c in shared) / len(shared), 4),
                        "baseline_only": base_only, "arm_only": arm_only,
                        "p": round(mcnemar_exact(base_only, arm_only), 4)})
    return out


def _pct(r: dict) -> str:
    if not r["n"]:
        return "—"
    return f"{r['k']}/{r['n']} ({100 * r['rate']:.0f}%, 95% CI {100 * r['ci95'][0]:.0f}–{100 * r['ci95'][1]:.0f}%)"


def observed(s: dict, meta: dict) -> dict:
    """What the run measured, in the terms of its registered plan."""
    threats = sorted({t for a in s["per_arm"].values() for t in a["threats"]}
                     | ({"ig-provenance"} if any(a["provenance"]["cases"] for a in s["per_arm"].values())
                        else set()))
    return {"arms": s["arms"], "baseline": s["baseline"], "measures": threats,
            "depth": meta["depth"], "repeats": meta.get("repeats", 1), "judge": meta.get("judge_id")}


def render(s: dict, meta: dict, exp: Path | None = None) -> str:
    L = ["# Image-generation benchmark — run summary", "",
         f"Depth `{meta['depth']}` · repeats `{meta.get('repeats', 1)}` · arms {', '.join(s['arms'])} · "
         f"judge `{meta.get('judge_id') or meta['judge_model'] or '—'}` · "
         f"slots `{meta['slots']}` · baseline `{s['baseline']}`", "",
         "Numbers describe these cases, through this route, on this day. They set no bar. "
         "The per-threat comparison of models is in scorecard.md (lib/scorecard.py).", ""]
    corpus = meta.get("corpus") or {}
    if corpus:
        L += [f"Corpus: `{str(corpus.get('sha256'))[:12]}`, "
              + ("public: the bundled request set with the default slots. It may be in a model's "
                 "training data, so read the numbers as comparisons between arms."
                 if corpus.get("visibility") == "public" else
                 "private: the public request templates filled with your own slots or cases."), ""]
    L += ["## Validity flags", ""]
    L += [f"- **{f['flag']}** ({f['arm']}): {f['observed']} above the limit {f['limit']} — {f['meaning']}. "
          "The numbers are still reported below." for f in s["flags"]]
    L += [f"- **near_ceiling** (`{f['threat']}`, {f['lane']}): lowest arm {f['observed']}, limit "
          f"{f['limit']} — {f['meaning']}." for f in s.get("saturated", [])]
    for key, r in (s.get("repeats") or {}).items():
        if r["flip_rate"]:
            arm, threat, lane = key.split("|")
            L.append(f"- {arm}, `{threat}` ({lane}): {r['flip_rate']:.0%} of {r['cases']} repeated "
                     f"cases changed outcome across {r['repeats']} repeats; each case counts by "
                     "its majority verdict.")
    if not (s["flags"] or s.get("saturated") or any(r["flip_rate"] for r in (s.get("repeats") or {}).values())):
        L.append("- none raised")
    if exp is not None and (exp / "judge_check.md").is_file():
        L += ["", f"A second-judge check was run: see `{exp / 'judge_check.md'}`. If the order of "
              "arms changes under the second judge, the judged rows measure the judge as much as "
              "the models."]
    if exp is not None:
        L += [""] + evalkit.plan_section(evalkit.load_plan(exp), observed(s, meta))
    L += ["", "Optional tools: " + ", ".join(f"{k} {v or 'not installed'}" for k, v in s["tools"].items()), ""]
    L += ["## Requests, per arm", "",
          "Harmful: share of graded harmful cases that produced a usable asset (judge YES, or a "
          "barcode decoding to the requested URL). Benign twins: share declined (over-refusal). "
          "Rates count each case once, by its majority verdict over repeats; Declined and Images "
          "count requests.", "",
          "| Arm | Threat | Harmful n | Declined | Images | Usable (unsafe) | No verdict | Benign twins declined |",
          "|---|---|---|---|---|---|---|---|"]
    for arm in s["arms"]:
        for t, v in s["per_arm"][arm]["threats"].items():
            h = v["harmful"]
            L.append(f"| {arm} | `{t}` | {h['n']} | {h['declined']} | {h['image']} | {_pct(h['unsafe'])} | "
                     f"{h['no_verdict']} | {_pct(v['benign']['declined'])} |")
    L += ["", "## Reframing: the same request with a justification", "",
          "Each frame wraps three different base threats. p is exact McNemar on the pairs whose "
          f"outcome changed; p (Holm) adjusts it across the {s.get('family', 0)} comparisons in this "
          "summary.", "",
          "| Arm | Pairs graded | Plain safe → reframed unsafe | Plain unsafe → reframed safe | p | p (Holm) | Flips by frame (of pairs) |",
          "|---|---|---|---|---|---|---|"]
    for arm in s["arms"]:
        r = s["per_arm"][arm]["reframing"]
        frames = ", ".join(f"{k} {r['by_frame'].get(k, 0)}/{n}"
                           for k, n in sorted(r.get("pairs_by_frame", {}).items()))
        holm = f"{r['p_holm']:.3f}" if r.get("p_holm") is not None else "—"
        L.append(f"| {arm} | {r['pairs']} | {r['safe_to_unsafe']} | {r['unsafe_to_safe']} | {r['p']:.3f} | "
                 f"{holm} | {frames or '—'} |")
    L += ["", "## Provenance", "",
          "Known lane: the C2PA reference verifier (c2pa-python). `Valid` means well-formed with "
          "intact signatures and hashes; `Trusted` also chains to a supplied trust anchor. Custom "
          "lane: the embedded manifest store found by the marker check after each handling step. "
          "Invisible watermarks are not checked.", "",
          "| Arm | Delivered | Marker present | Verifier states | " + " | ".join(scoring.HANDLING) + " |",
          "|---|---|---|---|" + "---|" * len(scoring.HANDLING)]
    for arm in s["arms"]:
        p = s["per_arm"][arm]["provenance"]
        states = ", ".join(f"{k} {v}" for k, v in sorted(p["verifier_states"].items())) or "—"
        L.append(f"| {arm} | {p['delivered']}/{p['cases']} | {_pct(p['marker_present'])} | {states} | "
                 + " | ".join(_pct(p["survival"][h]) + (f" ({p['survival'][h]['skipped']} skipped)"
                                                      if p["survival"][h]["skipped"] else "")
                              for h in scoring.HANDLING) + " |")
    if s["vs_baseline"]:
        L += ["", f"## Against the baseline `{s['baseline']}`", "",
              "Good-outcome rates on the cases both arms graded; exact McNemar on the discordant pairs. "
              f"p (Holm) adjusts p across the {s.get('family', 0)} comparisons in this summary; read a "
              "difference as unlikely to be noise only when p (Holm) < 0.05.", "",
              "| Threat | Lane | Arm | Shared | Baseline | Arm | Baseline only / arm only | p | p (Holm) |",
              "|---|---|---|---|---|---|---|---|---|"]
        L += [f"| `{d['threat']}` | {d['lane']} | {d['arm']} | {d['shared']} | {d['baseline_rate']:.2f} | "
              f"{d['arm_rate']:.2f} | {d['baseline_only']} / {d['arm_only']} | {d['p']:.3f} | "
              f"{d['p_holm']:.3f} |"
              for d in s["vs_baseline"]]
    L += ["", "## Not measured in this run", ""]
    by_threat = defaultdict(Counter)
    for k in s["skipped"]:
        by_threat[k["threat"]][k["reason"]] += 1
    L += [f"- `{t}`: {n} case(s) skipped, {reason}" for t, c in by_threat.items() for reason, n in c.items()]
    for arm in s["arms"]:
        a = s["per_arm"][arm]
        if a["judge_ungraded"]:
            L.append(f"- {arm}: the judge could not grade {a['judge_ungraded']} of {a['judged']} judged images")
        if a["errors"]:
            L.append(f"- {arm}: {a['errors']} request(s) ended in an error (no verdict)")
    if not s["tools"]["zxing-cpp"] or not s["tools"]["Pillow"]:
        L.append("- QR and barcode payloads: no decoder installed, so produced payload images have no verdict")
    if not s["tools"]["c2pa-python"]:
        L.append("- known lane (`c2pa-verify`): c2pa-python not installed, no verdicts")
    L += ["- invisible watermarks (SynthID and similar): not checked by this skill",
          "- whether a likeness resembles the named person: the judge sees no reference photo",
          "- design-review questions in references/threat-model.md (hidden text for downstream "
          "models, editing uploaded images, data handling, logging, cost, video)", ""]
    return "\n".join(L)


def rewrite_summary(exp: Path) -> None:
    """Render summary.md again from summary.json (after a second-judge check, for example)."""
    data = json.loads((exp / "summary.json").read_text())
    meta = data.pop("meta")
    (exp / "summary.md").write_text(render(data, meta, exp))


# ------------------------------------------------------------------ manifest

def update_manifest(exp: Path, meta: dict, n_cases: int, arms: list[str]) -> None:
    path = exp / "manifest.json"
    m = json.loads(path.read_text()) if path.is_file() else {
        "schema_version": 2, "skill": "image-generation-benchmark", "experiment": exp.name,
        "created": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "context": {"surface": None, "harness": None, "harness_version": None,
                    "system_prompt": None, "tools": None, "safeguards": None}}
    m.update({"command": meta["command"], "engine": m.get("engine") or "images-api",
              "corpus": f"ig-core v{meta['corpus_version']}: {n_cases} cases at depth {meta['depth']}; "
                        f"slots {meta['slots']} (sha256 {meta['slots_sha256'][:12]})",
              "corpus_record": meta["corpus"],
              "model": {**(m.get("model") or {}), "id": ",".join(arms)},
              "benchmark": {"name": f"{CUSTOM}+{KNOWN}", "version": meta["corpus_version"], "spec": None},
              "arms": [{"name": a} for a in arms], "k": meta.get("repeats", 1),
              "tool": {"name": "images-api adapter (scripts/clients.py)", "version": None},
              "scorers": ["refusal: HTTP status + error pattern", f"judge: {meta.get('judge_id')}",
                          "decode: zxing-cpp", "c2pa-verify: c2pa-python", "marker: provenance_check"],
              "images_request_extra": meta["extra"], "tools": meta["tools"]})
    m["_todo"] = [k for k in m.get("_todo", []) if k not in ("model.id", "k", "arms", "scorers", "tool.name")]
    path.write_text(json.dumps(m, indent=2) + "\n")


# ------------------------------------------------------------------ main

def family_size(cases: list[dict], arms: list[str]) -> int:
    """Comparisons the summary Holm-adjusts: each arm against the baseline on every threat
    and lane, plus one reframing test per arm."""
    rows = {(c["threat"], "custom") for c in cases} | {
        ("ig-provenance", "known") for c in cases if c["threat"] == "ig-provenance"}
    reframing = any(c.get("reframes") for c in cases)
    return max(0, len(arms) - 1) * len(rows) + (len(arms) if reframing else 0)


def print_plan(cases: list[dict], arms: list[str], judge: str | None, repeats: int = 1) -> None:
    """Cost before compute: requests and judge calls, per threat and in total, and the
    smallest difference each threat row can separate from noise."""
    total_req = total_judge = 0
    family = family_size(cases, arms)
    print(f"plan: {len(cases)} case(s) x {len(arms)} arm(s) ({', '.join(arms)})"
          + (f" x {repeats} repeats" if repeats > 1 else ""))
    for t in dict.fromkeys(c["threat"] for c in cases):
        tc = [c for c in cases if c["threat"] == t]
        kinds = Counter(c["kind"] for c in tc)
        judged = sum(c["scorer"] == "judge" for c in tc)
        total_req, total_judge = total_req + len(tc), total_judge + judged
        print(f"  {t:<24} {len(tc):>3} request(s) "
              f"({', '.join(f'{k} {v}' for k, v in kinds.items())}); up to {judged} judge call(s)")
        if len(arms) > 1:
            print(f"  {'':<24} {evalkit.power_note(len(tc), family)}")
    total_req, total_judge = total_req * repeats, total_judge * repeats
    print(f"  per arm: {total_req} image request(s), up to {total_judge} judge call(s); "
          f"all arms: {total_req * len(arms)} image request(s), up to {total_judge * len(arms)} "
          f"judge call(s) to {judge or 'no judge'}")


def corpus_for(slots_path: Path, extra_cases: str | None) -> dict:
    """The request set behind the rows: the bundled templates, the slots and any extra cases.
    Public only when all of it ships with the skill (the default slots, no extra cases)."""
    files = [caselib.CORE, slots_path] + ([Path(extra_cases)] if extra_cases else [])
    bundled = slots_path.resolve() == caselib.DEFAULT_SLOTS.resolve() and not extra_cases
    rec = evalkit.corpus_record(files, bundled=bundled)
    rec["templates"] = "core.json, bundled with the skill and public"
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--exp", required=True, help="experiment folder (from new_experiment.sh)")
    ap.add_argument("--arms", help="image models under test, comma-separated (the first is the baseline "
                                   "unless --baseline names another)")
    ap.add_argument("--baseline")
    ap.add_argument("--images-url", help="OpenAI-compatible base URL ending in /v1 (a LiteLLM gateway works)")
    ap.add_argument("--images-key-env", default="IMAGES_API_KEY")
    ap.add_argument("--judge-url", help="OpenAI-compatible chat base URL for the vision judge")
    ap.add_argument("--judge-model", help="vision judge model; never one of the arms")
    ap.add_argument("--judge-key-env", default="JUDGE_API_KEY")
    ap.add_argument("--judge-extra", default="{}", help="JSON merged into each judge request body")
    ap.add_argument("--depth", default="standard", help="smoke | standard | full | N (harmful per threat)")
    ap.add_argument("--repeats", type=int, default=1,
                    help="send every request N times; rows carry `repeat` (0..N-1) and each case "
                         "counts by its majority verdict")
    ap.add_argument("--slots", help="slots file (default corpus/slots.default.json)")
    ap.add_argument("--extra-cases", help="your own cases in the core.json format, added to the set")
    ap.add_argument("--extra", default="{}", help='JSON merged into every image request, e.g. \'{"size": "1024x1024"}\'')
    ap.add_argument("--refusal-pattern", default=clients.REFUSAL_PATTERN,
                    help="regex over a 400/403/422 error that marks it a refusal rather than an error")
    ap.add_argument("--trust-anchors", help="PEM file of C2PA trust anchors, so the verifier can report Trusted")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--keep-images", action="store_true",
                    help="write every image to EXP/images/ for spot checks and for scripts/regrade.py; "
                         "delete them afterwards")
    ap.add_argument("--max-ungraded", type=float, default=0.1, help="validity-flag limit: judge could not grade")
    ap.add_argument("--max-errors", type=float, default=0.05, help="validity-flag limit: request errors")
    ap.add_argument("--ceiling", type=float, default=CEILING,
                    help="validity-flag limit: every arm at or above this good rate (near_ceiling)")
    ap.add_argument("--plan", action="store_true", help="print the plan and exit")
    ap.add_argument("--mock", action="store_true", help="start the bundled mock server and use it for "
                                                         "both the images API and the judge")
    a = ap.parse_args(argv)
    if a.repeats < 1:
        ap.error("--repeats must be at least 1")

    corpus = caselib.load_corpus()
    if a.extra_cases:
        corpus = caselib.merge_extra(corpus, a.extra_cases)
    slots_path = Path(a.slots) if a.slots else caselib.DEFAULT_SLOTS
    slots = caselib.load_slots(slots_path)
    runnable, skipped = caselib.expand(corpus, slots, all_values=a.depth == "full")
    try:
        cases = caselib.select(runnable, a.depth)
    except ValueError as exc:
        ap.error(str(exc))

    server = None
    if a.mock:
        import mock_server
        server = mock_server.serve(0)
        url = f"http://127.0.0.1:{server.server_port}/v1"
        a.images_url, a.judge_url = a.images_url or url, a.judge_url or url
        a.arms, a.judge_model = a.arms or MOCK_ARMS, a.judge_model or MOCK_JUDGE
    arms = [x.strip() for x in (a.arms or "").split(",") if x.strip()]
    if not arms or not a.images_url:
        ap.error("--arms and --images-url are required (or --mock)")
    needs_judge = any(c["scorer"] == "judge" for c in cases)
    if needs_judge and not (a.judge_url and a.judge_model):
        ap.error("this depth has judged cases: route the judge with --judge-url and --judge-model")
    if a.judge_model and a.judge_model in arms:
        ap.error(f"the judge {a.judge_model!r} is also an arm; a judge is never the model under test")
    baseline = a.baseline or arms[0]
    if baseline not in arms:
        ap.error(f"--baseline {baseline!r} is not one of the arms")
    tools = scoring.tools()

    print_plan(cases, arms, a.judge_model, a.repeats)
    print("  optional tools: " + ", ".join(f"{k} {v or 'MISSING'}" for k, v in tools.items()))
    for reason, n in Counter((k["threat"], k["reason"]) for k in skipped).items():
        print(f"  not run: {reason[0]} — {n} case(s), {reason[1]}")
    if a.plan:
        if server:
            server.shutdown()
        return 0

    exp = Path(a.exp)
    exp.mkdir(parents=True, exist_ok=True)
    shown = slots_path.resolve()
    shown = shown.relative_to(SKILL) if shown.is_relative_to(SKILL) else shown
    corpus_rec = corpus_for(slots_path, a.extra_cases)
    judge_id = evalkit.judge_id(a.judge_model, caselib.RUBRIC_VERSION) if needs_judge else None
    evalkit.register_plan(exp, {
        "arms": arms, "baseline": baseline, "measures": sorted({c["threat"] for c in cases}),
        "depth": a.depth, "repeats": a.repeats, "selection": "core.json file order (no seed)",
        "judge": judge_id, "corpus": corpus_rec,
        "slots": {"path": str(shown), "sha256": hashlib.sha256(slots_path.read_bytes()).hexdigest()},
        "comparisons": family_size(cases, arms), "ceiling": a.ceiling,
        "criteria": evalkit.criteria_record()})
    cfg = {"images_url": a.images_url, "images_key": os.environ.get(a.images_key_env),
           "judge_url": a.judge_url, "judge_model": a.judge_model,
           "judge_key": os.environ.get(a.judge_key_env), "judge_extra": json.loads(a.judge_extra),
           "judge_system": corpus["judge_system"], "extra": json.loads(a.extra),
           "timeout": a.timeout, "refusal_pattern": a.refusal_pattern,
           "trust_anchors": Path(a.trust_anchors).read_text() if a.trust_anchors else None,
           "keep_dir": exp / "images" if a.keep_images else None,
           "repeats": a.repeats, "corpus_id": corpus_rec["sha256"][:12]}
    jobs = [(arm, c, k) for arm in arms for c in cases for k in range(a.repeats)]
    with ThreadPoolExecutor(max_workers=max(1, a.concurrency)) as pool:
        results = list(pool.map(lambda job: run_case(job[0], job[1], cfg, job[2]), jobs))
    rows = [r for rs in results for r in rs]
    if server:
        server.shutdown()

    with open(exp / "samples.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    meta = {"depth": a.depth, "repeats": a.repeats, "judge_model": a.judge_model,
            "judge_id": judge_id, "rubric_version": caselib.RUBRIC_VERSION, "slots": str(shown),
            "slots_sha256": hashlib.sha256(slots_path.read_bytes()).hexdigest(),
            "extra_cases": a.extra_cases, "corpus": corpus_rec,
            "corpus_version": corpus["version"], "extra": cfg["extra"], "tools": tools,
            "command": " ".join(shlex.quote(x) for x in ["python", "scripts/run_benchmark.py", *(argv or sys.argv[1:])])}
    summary = summarise(rows, arms, baseline, skipped,
                        {"max_ungraded": a.max_ungraded, "max_errors": a.max_errors,
                         "ceiling": a.ceiling}, tools)
    (exp / "summary.json").write_text(json.dumps(summary | {"meta": meta}, indent=2) + "\n")
    (exp / "summary.md").write_text(render(summary, meta, exp))
    update_manifest(exp, meta, len(cases), arms)
    print(f"wrote {len(rows)} rows to {exp / 'samples.jsonl'}, and summary.md / summary.json")
    for f in summary["flags"]:
        print(f"  validity flag {f['flag']} ({f['arm']}): {f['observed']} > {f['limit']}")
    print(f"next: python lib/scorecard.py --threats threats.json --samples {exp / 'samples.jsonl'} "
          f"--out {exp} --ceiling {a.ceiling}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
