#!/usr/bin/env python3
"""Phoenix Ω∞ Manifestation Core: proposal, append-only event ledger, verification.
Generated output is recorded as a proposal. This service does not execute model code.
"""
from __future__ import annotations
import hashlib, json, os, sqlite3
from contextlib import contextmanager, asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

DB_PATH = Path(os.environ.get("MANIFEST_DB", "sovereign_manifestation.db"))
MODEL = os.environ.get("GEMINI_MODEL", "gemini-4-argon")

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield

app = FastAPI(title="Phoenix Ω∞ Manifestation Core", version="4.3.0", lifespan=lifespan)

@contextmanager
def db():
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS manifest_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            intent TEXT NOT NULL,
            output TEXT NOT NULL,
            interaction_id TEXT,
            digest TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            detail TEXT NOT NULL,
            previous_digest TEXT,
            digest TEXT NOT NULL
        )""")

class ManifestRequest(BaseModel):
    intent: str = Field(min_length=1, max_length=12000)

class AuditRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=120)
    detail: str = Field(min_length=1, max_length=4000)

def get_ai_client():
    from google import genai
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

@app.get("/health")
def health() -> dict[str, Any]:
    init_db()
    with db() as conn:
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        count = conn.execute("SELECT COUNT(*) FROM manifest_ledger").fetchone()[0]
    return {"status": "healthy", "database": str(DB_PATH), "journal_mode": journal,
            "manifest_records": count, "model_configured": bool(os.getenv("GEMINI_API_KEY")),
            "execution_policy": "proposal-only"}

@app.post("/audit")
def append_audit(req: AuditRequest) -> dict[str, Any]:
    init_db()
    timestamp = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        # Serialize the read-link-write transaction so concurrent writers cannot fork the chain.
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute("SELECT digest FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
        prev_digest = previous["digest"] if previous else None
        payload = {"timestamp": timestamp, "event_type": req.event_type,
                   "detail": req.detail, "previous_digest": prev_digest}
        digest = canonical_digest(payload)
        cur = conn.execute("INSERT INTO audit_events(timestamp,event_type,detail,previous_digest,digest) VALUES(?,?,?,?,?)",
                           (timestamp, req.event_type, req.detail, prev_digest, digest))
        return {"status": "appended", "event_id": cur.lastrowid, "digest": digest,
                "previous_digest": prev_digest}

@app.get("/audit/verify")
def verify_audit() -> dict[str, Any]:
    init_db()
    with db() as conn:
        rows = conn.execute("SELECT * FROM audit_events ORDER BY id").fetchall()
    expected_prev = None
    for row in rows:
        payload = {"timestamp": row["timestamp"], "event_type": row["event_type"],
                   "detail": row["detail"], "previous_digest": row["previous_digest"]}
        if row["previous_digest"] != expected_prev or canonical_digest(payload) != row["digest"]:
            return {"verified": False, "checked": row["id"], "reason": "chain_or_digest_mismatch"}
        expected_prev = row["digest"]
    return {"verified": True, "events_checked": len(rows), "head_digest": expected_prev}

@app.post("/manifest")
def manifest(req: ManifestRequest) -> dict[str, Any]:
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(status_code=503, detail="Set GEMINI_API_KEY to enable generation.")
    try:
        ai_client = get_ai_client()
        result = ai_client.interactions.create(
            model=MODEL,
            input=("Create a structured implementation proposal with plan, tests, risks, "
                   "and required approvals. Do not claim execution. Do not emit secrets.\n\n"
                   f"INTENT:\n{req.intent}"),
        )
        output = getattr(result, "output_text", None)
        if not output:
            raise ValueError("No output_text returned; validate SDK/API response schema.")
        timestamp = datetime.now(timezone.utc).isoformat()
        interaction_id = getattr(result, "id", None)
        payload = {"timestamp": timestamp, "intent": req.intent, "output": output,
                   "interaction_id": interaction_id}
        digest = canonical_digest(payload)
        with db() as conn:
            cur = conn.execute("INSERT INTO manifest_ledger(timestamp,intent,output,interaction_id,digest) VALUES(?,?,?,?,?)",
                               (timestamp, req.intent, output, interaction_id, digest))
            record_id = cur.lastrowid
        append_audit(AuditRequest(event_type="manifest.proposal_recorded",
                                  detail=json.dumps({"record_id": record_id, "digest": digest})))
        return {"status": "PROPOSAL_RECORDED", "record_id": record_id,
                "interaction_id": interaction_id, "sha256": digest, "output": output,
                "execution_performed": False}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Generation or persistence failed: {type(exc).__name__}") from exc

@app.get("/ledger/{record_id}")
def read_record(record_id: int) -> dict[str, Any]:
    init_db()
    with db() as conn:
        row = conn.execute("SELECT * FROM manifest_ledger WHERE id=?", (record_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return dict(row)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("manifest_core:app", host="127.0.0.1", port=8000)
