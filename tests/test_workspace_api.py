import json
from threading import Event

from test_phase4_api import client as client

from scripts.phase3_fixtures import create_pdf
from vision_rag.api import routes, workspace
from vision_rag.generate.events import checkpoint


def test_saved_chat_scope_event_replay_and_viewer(client, tmp_path, monkeypatch):
    from vision_rag.models import gemini_generator

    class Provider:
        def close(self):
            pass

        def generate_grounded_stream(self, query, evidence, images, delta, cancelled):
            for text in ("Revenue ", "is ", "120 units."):
                checkpoint(cancelled)
                delta(text)
            return {
                "status": "supported",
                "claims": [
                    {"text": "Revenue is 120 units.", "citations": [evidence[0]["id"]]}
                ],
            }

    monkeypatch.setattr(gemini_generator, "GeminiGenerator", lambda **_: Provider())
    pdf = create_pdf(tmp_path / "report.pdf", ("text", "table"))
    job = client.post(
        "/api/v1/ingest", files={"file": ("quoted' <report>.pdf", pdf.read_bytes())}
    ).json()
    library = routes.get_library()
    library.process_one()
    library.retrieval.queue()
    library.process_one()
    c = client.post(
        "/api/v1/conversations", json={"document_ids": [job["document_id"]]}
    ).json()
    turn = client.post(
        f"/api/v1/conversations/{c['id']}/messages", json={"query": "ALPHA42"}
    ).json()
    stream = client.get(f"/api/v1/messages/{turn['id']}/events")
    assert stream.status_code == 200
    events = [
        json.loads(line[6:])
        for line in stream.text.splitlines()
        if line.startswith("data: ")
    ]
    assert len([e for e in events if e.get("provisional") and e.get("text")]) == 3
    assert events[-1]["state"] == "completed"
    result = events[-1]["result"]
    assert result["claims"][0]["citations"] == [result["sources"][0]["evidence_id"]]
    ids = [
        int(line[4:]) for line in stream.text.splitlines() if line.startswith("id: ")
    ]
    assert ids == list(range(1, len(ids) + 1))
    assert not client.get(f"/api/v1/messages/{turn['id']}/events?after={ids[-1]}").text
    saved = client.get(f"/api/v1/conversations/{c['id']}").json()
    assert saved["messages"][0]["request"]["document_ids"] == [job["document_id"]]
    assert (
        client.patch(
            f"/api/v1/conversations/{c['id']}",
            json={
                "viewer": {
                    "version_id": job["version_id"],
                    "page": 2,
                    "zoom": 1.5,
                    "scroll_top": 75,
                }
            },
        ).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/versions/{job['version_id']}/info").json()["page_count"]
        == 2
    )
    assert (
        client.patch(
            f"/api/v1/conversations/{c['id']}",
            json={"viewer": {"version_id": job["version_id"], "page": 3}},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/maintenance", json={"action": "history", "confirmation": "CLEAR"}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/conversations").json() == []
    assert client.get("/api/v1/documents").json()


def test_turn_cancellation_discards_late_results_and_allows_retry(client, monkeypatch):
    entered, release = Event(), Event()

    def delayed(request, emit, cancelled):
        entered.set()
        release.wait(5)
        checkpoint(cancelled)
        return routes.QueryResponse(answer="completed", sources=[])

    monkeypatch.setattr(routes, "execute_query", delayed)
    c = client.post("/api/v1/conversations", json={}).json()
    turn = client.post(
        f"/api/v1/conversations/{c['id']}/messages", json={"query": "Question"}
    ).json()
    assert entered.wait(3)
    assert (
        client.post(
            f"/api/v1/conversations/{c['id']}/messages", json={"query": "Second"}
        ).status_code
        == 409
    )
    assert client.post(f"/api/v1/messages/{turn['id']}/cancel").status_code == 200
    release.set()
    workspace.stop_turns()
    saved = client.get(f"/api/v1/messages/{turn['id']}").json()
    assert saved["state"] == "cancelled" and saved["result"] is None
    retry = client.post(
        f"/api/v1/conversations/{c['id']}/messages", json={"query": "Question"}
    )
    assert retry.status_code == 202
    workspace.stop_turns()


def test_workspace_validates_missing_scope_and_clears_on_reset(client):
    assert (
        client.post(
            "/api/v1/conversations", json={"document_ids": ["missing"]}
        ).status_code
        == 404
    )
    c = client.post("/api/v1/conversations", json={}).json()
    assert (
        client.patch(
            f"/api/v1/conversations/{c['id']}", json={"title": None}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/maintenance", json={"action": "reset", "confirmation": "DELETE"}
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/conversations/{c['id']}").status_code == 404
