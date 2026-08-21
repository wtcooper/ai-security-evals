#!/usr/bin/env python3
"""Translate ground_truth.jsonl through a mutate.py rename map (files + function names) so
matching against the mutant works.  python3 translate_gt.py gt.jsonl rename_map.json > gt.mutant.jsonl"""
import json
import re
import sys

gt = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
m = json.load(open(sys.argv[2]))
ids, files = m.get("identifiers", {}), m.get("files", {})
pat = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted((k for k in ids if not k.startswith("/")), key=len, reverse=True)) + r")\b") if ids else None
for g in gt:
    if g.get("file") in files:
        g["file"] = files[g["file"]]
    elif pat and g.get("file"):
        g["file"] = pat.sub(lambda x: ids[x.group(1)], g["file"])
    if pat and g.get("function"):
        g["function"] = pat.sub(lambda x: ids[x.group(1)], g["function"])
    print(json.dumps(g))
