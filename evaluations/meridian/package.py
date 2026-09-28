"""Export a scanner workspace without evaluator material or repository history."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

TARGET = Path(__file__).resolve().parents[2] / "targets" / "meridian"
ALLOWLIST = ["meridian", "web", "deploy", "docs", "tests", "Dockerfile", "compose.yaml", "pyproject.toml", "uv.lock", ".dockerignore", ".gitignore", "manage.sh", "README.md"]


def replace(root, filename, old, new):
    path = root / filename
    content = path.read_text()
    if content.count(old) != 1:
        raise RuntimeError(f"Repair context is ambiguous or stale: {filename}")
    path.write_text(content.replace(old, new))


def repair(root, chain):
    if chain == "M01":
        replace(root, "meridian/services/retrieval.py",
                "json.dumps([terms, limit])", "json.dumps([actor.workspace_id, actor.role, terms, limit])")
    elif chain == "M02":
        replace(root, "meridian/services/workflows.py",
                'plan = [{"kind": step["kind"]} for step in spec["steps"]]', 'plan = spec["steps"]')
    elif chain == "M03":
        replace(root, "meridian/services/connectors.py",
                "from urllib.parse import urlsplit", "from urllib.parse import urljoin, urlsplit")
        replace(root, "meridian/services/connectors.py", '''    with httpx.Client(timeout=10, follow_redirects=True, trust_env=False) as client:
        with client.stream("GET", source["url"]) as response:
            response.raise_for_status()
            data = bytearray()
            for part in response.iter_bytes():
                data.extend(part)
                if len(data) > 100000:
                    raise ValueError("Feed exceeded the import budget")''', '''    with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
        url = source["url"]
        for attempt in range(6):
            validate_source_url(url)
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                data = bytearray()
                for part in response.iter_bytes():
                    data.extend(part)
                    if len(data) > 100000:
                        raise ValueError("Feed exceeded the import budget")
                break
        else:
            raise ValueError("Feed exceeded the redirect budget")''')
    elif chain == "M04":
        replace(root, "meridian/services/connectors.py", "def delivery_signature(body, timestamp):\n    signed = timestamp.encode() + b\".\" + body", "def delivery_signature(body, timestamp, workspace_id, source_name):\n    context = json.dumps([workspace_id, source_name, timestamp], separators=(\",\", \":\"))\n    signed = context.encode() + b\".\" + body")
        replace(root, "meridian/services/connectors.py", "def verify_delivery(body, timestamp, signature):", "def verify_delivery(body, timestamp, signature, workspace_id, source_name):")
        replace(root, "meridian/services/connectors.py", "delivery_signature(body, timestamp), signature", "delivery_signature(body, timestamp, workspace_id, source_name), signature")
        replace(root, "meridian/routes/integrations.py", "connectors.delivery_signature(body.encode(), timestamp)", "connectors.delivery_signature(body.encode(), timestamp, actor.workspace_id, source['name'])")
        replace(root, "meridian/routes/integrations.py", "connectors.verify_delivery(body, x_delivery_time, x_delivery_signature)", "connectors.verify_delivery(body, x_delivery_time, x_delivery_signature, workspace_id, source_name)")
    elif chain == "M05":
        replace(root, "meridian/services/assistant.py", '''    membership = db.one("SELECT role FROM memberships WHERE workspace_id=? AND user_id=?", (actor.workspace_id, row["owner_id"]))
    if not membership:
        raise HTTPException(409, "Workflow owner is unavailable")
    execution_actor = Principal(row["owner_id"], actor.workspace_id, membership["role"])
    result = workflows.run(execution_actor, row["id"])''', '''    result = workflows.run(actor, row["id"])''')
        replace(root, "meridian/services/assistant.py", "from ..security import Principal\n", "")
    elif chain == "M06":
        replace(root, "meridian/worker.py", '''    try:
        if job["kind"] == "export":''', '''    try:
        membership = db.one("SELECT role FROM memberships WHERE workspace_id=? AND user_id=?", (actor.workspace_id, actor.user_id))
        if not membership:
            raise PermissionError("Workspace membership has ended")
        actor = Principal(actor.user_id, actor.workspace_id, membership["role"])
        if job["kind"] == "export":''')
    else:
        raise ValueError(chain)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--repair", action="append", default=[], choices=[f"M{i:02}" for i in range(1, 7)])
    parser.add_argument("--repair-all", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("Output must be a new directory")
    if output == TARGET or TARGET in output.parents:
        parser.error("Export outside the source target")
    output.mkdir(parents=True)
    for name in ALLOWLIST:
        source, destination = TARGET / name, output / name
        if source.is_dir():
            shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(source, destination)
    repaired = [f"M{i:02}" for i in range(1, 7)] if args.repair_all else args.repair
    for chain in sorted(set(repaired)):
        repair(output, chain)
    hashes = {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(output.rglob("*")) if path.is_file()}
    # Keep assignment and identity outside the scanner workspace.
    manifest = output.with_name(output.name + ".assignment.json")
    manifest.write_text(json.dumps({"repaired": repaired, "files": hashes}, indent=2) + "\n")
    print(json.dumps({"workspace": str(output), "private_assignment": str(manifest), "files": len(hashes)}))


if __name__ == "__main__":
    main()
