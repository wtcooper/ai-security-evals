import sqlite3, json, os

DB = os.path.expanduser("~/.promptfoo/promptfoo.db")
EVAL_ID = "eval-Nbw-2026-06-06T20:44:07"

conn = sqlite3.connect(DB)
rows = conn.execute(
    "SELECT id, response FROM eval_results WHERE eval_id = ?", (EVAL_ID,)
).fetchall()

for result_id, response_json in rows:
    r = json.loads(response_json)
    meta = r.get("metadata", {})
    messages = meta.get("messages", [])
    rounds = meta.get("crescendoRoundsCompleted", 0)
    backtracks = meta.get("crescendoBacktrackCount", 0)
    success = meta.get("crescendoResult", False)
    stop = meta.get("stopReason", "")

    print(f"\n{'='*80}")
    print(f"Result: {result_id}  |  rounds={rounds}  backtracks={backtracks}  success={success}  stop={stop}")
    print(f"{'='*80}")
    for i, msg in enumerate(messages):
        role = msg["role"].upper()
        content = msg["content"][:500] + "..." if len(msg["content"]) > 500 else msg["content"]
        print(f"\n[{i+1}] {role}:\n{content}")

conn.close()
