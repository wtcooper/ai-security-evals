# Using a public audio jailbreak set instead of synthesised speech

The default known lane speaks the vendored AdvBench and XSTest text with one local voice.
Published audio sets add multi-voice clips and attack audio that this skill does not
generate. They are large, so nothing is vendored: sample a slice at a pinned revision,
convert it, and run it through `import_clips.py`. Facts below were read from the dataset
pages and papers on 2026-11-14 and re-checked against the Hugging Face API on 2026-11-21.

**Which one.** The known lane is capped at two published benchmarks. If a review wants
published audio, use **JALMBench `HarmfulQuery/AHarm.parquet`** in place of AdvBench for the
`vm-spoken-harm` row (it is one 53 MB file with the words of every clip, so the text arm and
the judge work), and keep XSTest for `vm-over-refusal`. Its rows get the benchmark id
`jalmbench-aharm` in `samples.jsonl` and the scorecard shows it on that row. The
Jailbreak-AudioBench sets are listed for reference only.

## What the published work found (so the result has context)

- **JALMBench** (arXiv 2505.17568, v3). Across 12 audio language models, plain harmful
  queries with no attack succeeded on average 21.5% of the time spoken and 17.0% typed. The
  direction was not the same for every model: the paper names two with higher success in text.
- **"Beyond Text"** (arXiv 2510.20223, a workshop paper by authors at a security vendor).
  It applies echo, pitch, speed and volume changes to spoken requests on three audio models.
  Its headline is that models with about 0% attack success on text exceeded 75% under
  perceptually modified inputs (image and audio transformations together). For audio the
  highest figures are for one content domain (CBRN): echo reached 75.0% and 74.0% on two
  models. For general harmful content it reports most transformations under 10%, and
  untransformed speech near zero for most categories (19.0% and 25.0% on two models for
  CBRN).
- **Jailbreak-AudioBench** (arXiv 2501.13772). Its toolbox edits spoken requests for
  emphasis, speed, intonation, tone, background noise, celebrity accent and emotion.

None of these tested the realtime models this skill was built for. They are a reason to
measure, not a prediction.

## The sets

| Set | Hugging Face id, pinned revision | Licence (dataset card) | Size | Columns |
|---|---|---|---|---|
| JALMBench | `AnonymousUser000/JALMBench` @ `53da5217aad7b5640dd0bed5f58b79b19dde7fb2`; not gated | CC-BY-4.0 | 1,460 files, about 138 GB; the plain harmful audio is one file, `HarmfulQuery/AHarm.parquet`, 52,770,540 bytes, 246 rows (LFS sha256 `4bc1a95c...`) | `id`, `text`, `original_text`, `source`, `audio` (a struct with `array` of floats and `sampling_rate`) |
| Jailbreak-AudioBench | `researchtopic/Jailbreak-AudioBench` @ `9a0fc687ebaebb47bd4fcc3223a07def399eacd3` | CC-BY-4.0 | 85 parquet files, about 89 GB, 316,625 rows | `audio` (WAV bytes), `filepath` |
| Jailbreak-AudioBench-Plus | `researchtopic/Jailbreak-AudioBench-Plus` @ `732a25c494fbc8b198769efcac09f2f8e25684bb`; not gated | CC-BY-4.0 | 43 parquet files of about 1 GB, 42.2 GB in all, 142,674 rows; plus `datasets_text/` CSVs (`id,question,target,category`) | `audio` (WAV bytes), `filepath` |

Per-file access was checked: a byte-range request for the first four bytes of `AHarm.parquet`
at the pinned revision returned the parquet magic `PAR1`, so the file can be fetched alone
without the rest of the repository.

Read before use:
- The licence above is the one on the dataset page. JALMBench rows come from AdvBench,
  HarmBench, JailbreakBench and MM-SafetyBench, and the AudioBench file paths name AdvBench
  and MM-SafetyBench. The licences of those underlying sets were not checked here.
- JALMBench `id` values repeat across `source`. Build case ids from both.
- The two AudioBench sets have **no text column** in their audio files. Without the words
  of each clip you cannot run the text arm or show the judge what was asked. The Plus
  repository now also holds `datasets_text/Explicit/*.csv` and `datasets_text/Implicit/*.csv`
  (for example `Explicit_Advbench.csv` with `id,question,target,category`); matching clips to
  those rows by `filepath` was not attempted here.
- The AudioBench "accent" clips imitate the voices of named public figures (the file paths
  carry the names). Decide whether your organisation wants those in a test; filter on
  `filepath` if not.
- These sets contain harmful requests only. Keep the benign cases from this skill's corpus
  in a separate run, or the refusal rate on safe requests goes unmeasured.

## Sampling JALMBench plain harmful queries (run on six clips on 2026-11-14; not re-run since)

Needs `pyarrow` in the skill's environment. The download is one 53 MB file.

```
curl -L -o AHarm.parquet \
  https://huggingface.co/datasets/AnonymousUser000/JALMBench/resolve/53da5217aad7b5640dd0bed5f58b79b19dde7fb2/HarmfulQuery/AHarm.parquet
sha256sum AHarm.parquet   # 4bc1a95c9d66c7d0e68196c5fca0edaf3b357a0a8561452bda2d1dff8596d604
```

```python
# jalm_to_index.py <AHarm.parquet> <how many> <seed> <output dir>
import array, hashlib, json, sys, wave
import pyarrow.parquet as pq

parquet, n, seed, out = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
rows = pq.ParquetFile(parquet).read().to_pylist()
rows.sort(key=lambda r: hashlib.sha256(f"{seed}:{r['source']}:{r['id']}".encode()).hexdigest())
with open(f"{out}/rows.jsonl", "w") as index:
    for r in rows[:n]:
        pcm = array.array("h", (max(-32768, min(32767, round(x * 32767)))
                                for x in r["audio"]["array"]))
        cid = f"jalm-{r['source']}-{r['id']}"
        with wave.open(f"{out}/{cid}.wav", "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(r["audio"]["sampling_rate"])
            w.writeframes(pcm.tobytes())
        index.write(json.dumps({"id": cid, "type": "harmful", "prompt": r["text"],
                                "audio": f"{cid}.wav", "category": r["source"]}) + "\n")
```

Then:

```
python import_clips.py --index <dir>/rows.jsonl --out <clips dir> \
  --source-name "JALMBench AHarm" --source-license CC-BY-4.0
python run_benchmark.py --corpus <clips dir>/cases.jsonl --clips <clips dir> \
  --lanes known --arms text,speech --depth full --model <model> --judge <judge> --out <EXP>
```

Use `--source-name "JALMBench AHarm"` so the rows carry the benchmark id `jalmbench-aharm`.

The clips in that file are 16 kHz or 24 kHz; `import_clips.py` resamples to 24 kHz. To add
this skill's perturbations to imported clips, run
`python perturb.py --clips <clips dir>/manifest.json --arms noise,echo` and list those arms.

## Sampling Jailbreak-AudioBench-Plus (the read was verified on three rows; the run was not)

With the `datasets` package, streaming avoids downloading the 1 GB files whole, and leaving
the audio undecoded gives the original WAV bytes (the three rows read here were mono 16-bit
PCM at 24 kHz):

```python
from datasets import load_dataset, Audio
ds = load_dataset("researchtopic/Jailbreak-AudioBench-Plus", split="train", streaming=True)
ds = ds.cast_column("audio", Audio(decode=False))
for row in ds.take(50):
    open(row["filepath"].replace("\\", "_"), "wb").write(row["audio"]["bytes"])
```

`take(50)` returns the first rows, which are all one edit type; shuffle with a buffer or
skip to spread across types. Supply the text for each clip yourself (see above) before
building `rows.jsonl`. Without text, run `--arms speech` only and read the result as attack
success on that audio, with no modality gap. The judge then needs a `prompt` to grade
against, so a clip without its words cannot be graded.

## Reporting

Record the dataset id, the file or row range, the seed and the sample size in the experiment
manifest. A sample of a public set is a sample: report its interval, and do not present it as
the published benchmark's score.
