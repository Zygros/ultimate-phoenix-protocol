import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
import manifest_core as core

def setup_function():
    core.DB_PATH = Path("test_manifest.db")
    if core.DB_PATH.exists(): core.DB_PATH.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(core.DB_PATH) + suffix)
        if p.exists(): p.unlink()
    core.init_db()

def test_health_and_wal():
    r = TestClient(core.app).get("/health")
    assert r.status_code == 200
    assert r.json()["journal_mode"].lower() == "wal"
    assert r.json()["execution_policy"] == "proposal-only"

def test_audit_chain_and_tamper_detection():
    c = TestClient(core.app)
    a = c.post("/audit", json={"event_type":"test.one","detail":"first"})
    b = c.post("/audit", json={"event_type":"test.two","detail":"second"})
    assert a.status_code == b.status_code == 200
    assert b.json()["previous_digest"] == a.json()["digest"]
    v = c.get("/audit/verify").json()
    assert v["verified"] is True and v["events_checked"] == 2
    with core.db() as conn:
        conn.execute("UPDATE audit_events SET detail='tampered' WHERE id=1")
    assert c.get("/audit/verify").json()["verified"] is False

def test_manifest_requires_key_without_calling_provider(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = TestClient(core.app).post("/manifest", json={"intent":"test"})
    assert r.status_code == 503

def test_missing_record_404():
    r = TestClient(core.app).get("/ledger/999")
    assert r.status_code == 404

def test_manifest_records_proposal_and_audit(monkeypatch):
    class FakeResult:
        output_text = "plan: run unit tests"
        id = "fake-interaction-001"
    class FakeInteractions:
        def create(self, **kwargs):
            assert kwargs["model"] == core.MODEL
            return FakeResult()
    class FakeClient:
        interactions = FakeInteractions()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(core, "get_ai_client", lambda: FakeClient())
    c = TestClient(core.app)
    r = c.post("/manifest", json={"intent":"test proposal"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "PROPOSAL_RECORDED"
    assert body["execution_performed"] is False
    assert len(body["sha256"]) == 64
    record = c.get(f"/ledger/{body['record_id']}")
    assert record.status_code == 200
    assert record.json()["output"] == "plan: run unit tests"
    assert c.get("/audit/verify").json()["verified"] is True

def test_concurrent_audit_writes_keep_single_chain():
    from concurrent.futures import ThreadPoolExecutor
    c = TestClient(core.app)
    def write_event(i):
        return c.post("/audit", json={
            "event_type": "test.concurrent", "detail": f"event-{i}"
        })
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(write_event, range(40)))
    assert all(r.status_code == 200 for r in responses)
    verified = c.get("/audit/verify").json()
    assert verified["verified"] is True
    assert verified["events_checked"] == 40

def test_audit_input_bounds():
    c = TestClient(core.app)
    assert c.post("/audit", json={"event_type":"", "detail":"x"}).status_code == 422
    assert c.post("/audit", json={"event_type":"x", "detail":"y" * 4001}).status_code == 422
