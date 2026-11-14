# Using a public audio jailbreak set instead of synthesised speech

The default run speaks this skill's own corpus with one local voice. Published audio sets
add human-recorded or multi-voice clips and attack audio that this skill does not generate.
They are large, so nothing is vendored: sample a slice, convert it, and run it through
`import_clips.py`. All facts below were read from the dataset pages and papers on 2026-11-14.

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

| Set | Hugging Face id | Licence on the dataset page | Size | Columns |
|---|---|---|---|---|
| JALMBench | `AnonymousUser000/JALMBench` | CC-BY-4.0 | about 138 GB in total; the plain harmful audio is one 53 MB file, `HarmfulQuery/AHarm.parquet` (246 rows) | `id`, `text`, `original_text`, `source`, `audio` (a struct with `array` of floats and `sampling_rate`) |
| Jailbreak-AudioBench | `researchtopic/Jailbreak-AudioBench` | CC-BY-4.0 | about 89 GB, 316,625 rows | `audio` (WAV bytes), `filepath` |
| Jailbreak-AudioBench-Plus | `researchtopic/Jailbreak-AudioBench-Plus` | CC-BY-4.0 | about 42 GB in 43 files of roughly 1 GB, 142,674 rows | `audio` (WAV bytes), `filepath` |

Read before use:
- The licence above is the one on the dataset page. JALMBench rows come from AdvBench,
  HarmBench, JailbreakBench and MM-SafetyBench, and the AudioBench file paths name AdvBench
  and MM-SafetyBench. The licences of those underlying sets were not checked here.
- JALMBench `id` values repeat across `source`. Build case ids from both.
- The two AudioBench sets have **no text column**. Without the words of each clip you cannot
  run the text arm or show the judge what was asked. The paper points to
  `github.com/Researchtopic/Code-Jailbreak-AudioBench` for the project code; matching clips
  to text from there was not attempted here.
- The AudioBench "accent" clips imitate the voices of named public figures (the file paths
  carry the names). Decide whether your organisation wants those in a test; filter on
  `filepath` if not.
- These sets contain harmful requests only. Keep the benign cases from this skill's corpus
  in a separate run, or the refusal rate on safe requests goes unmeasured.

## Sampling JALMBench plain harmful queries (verified here on six clips)

Needs `pyarrow` in the skill's environment. The download is one 53 MB file.

```
curl -L -o AHarm.parquet \
  https://huggingface.co/datasets/AnonymousUser000/JALMBench/resolve/main/HarmfulQuery/AHarm.parquet
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
  --arms text,speech --depth full --model <model> --judge <judge> --out <EXP>
```

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
