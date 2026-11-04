import csv
import io
import json

from test_phase4_api import client as client
from test_version_comparison import Provider

from scripts.phase3_fixtures import create_pdf
from vision_rag.api import routes
from vision_rag.storage.findings import Findings
from vision_rag.storage.metadata import Metadata


def compare(client, tmp_path, monkeypatch):
    from vision_rag.models import gemini_generator

    class ComparisonProvider(Provider):
        def close(self):
            pass

    monkeypatch.setattr(
        gemini_generator, "GeminiGenerator", lambda **_: ComparisonProvider()
    )
    path = create_pdf(tmp_path / "report.pdf", ("text", "table"))
    jobs = []
    for name in ("=Report.csv.pdf", "Other 'report'.pdf"):
        jobs.append(
            client.post(
                "/api/v1/ingest",
                files={"file": (name, path.read_bytes() + name.encode())},
            ).json()
        )
        routes.get_library().process_one()
    routes.get_library().retrieval.queue()
    routes.get_library().process_one()
    response = client.post(
        "/api/v1/comparisons",
        json={
            "question": "Compare ALPHA42",
            "version_ids": [j["version_id"] for j in jobs],
            "fields": ["Revenue", "Missing metric"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json(), jobs


def test_compare_save_reopen_and_export_links_in_every_format(
    client, tmp_path, monkeypatch
):
    draft, jobs = compare(client, tmp_path, monkeypatch)
    key = draft["id"]
    assert draft["state"] == "draft" and client.get("/api/v1/findings").json() == []
    assert client.get(f"/api/v1/findings/{key}/export").status_code == 409
    saved = client.post(f"/api/v1/findings/{key}/save").json()
    assert saved["state"] == "saved"
    assert (
        client.patch(f"/api/v1/findings/{key}", json={"content": {}}).status_code == 422
    )
    reviewed = client.patch(f"/api/v1/findings/{key}", json={"reviewed": True}).json()
    assert reviewed["content_hash"] == draft["content_hash"]
    data = client.get(f"/api/v1/findings/{key}/export?format=json").json()
    assert data["content"]["table"]["cells"][0]["unit"] == "units"
    assert all(
        "/versions/" in s["original_url"] and "#page=" in s["original_url"]
        for s in data["source_links"]
    )
    csv_response = client.get(f"/api/v1/findings/{key}/export?format=csv")
    rows = list(csv.DictReader(io.StringIO(csv_response.text)))
    assert len(rows) == 4
    assert rows[0]["filename"].startswith("'=")
    assert json.loads(rows[0]["value_json"]) == "120"
    assert json.loads(rows[0]["source_links"])[0]["version_id"] == jobs[0]["version_id"]
    markdown = client.get(f"/api/v1/findings/{key}/export?format=md").text
    assert "semantic support remains unverified" in markdown
    assert jobs[0]["version_id"] in markdown and "#page=1" in markdown
    assert (
        client.post(
            "/api/v1/maintenance", json={"action": "history", "confirmation": "CLEAR"}
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/findings/{key}").status_code == 200
    assert (
        client.post(
            "/api/v1/maintenance", json={"action": "reset", "confirmation": "DELETE"}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/findings").json() == []


def test_deleted_sources_and_other_workspaces_cannot_be_exported(
    client, tmp_path, monkeypatch
):
    finding, jobs = compare(client, tmp_path, monkeypatch)
    key = finding["id"]
    client.post(f"/api/v1/findings/{key}/save")
    metadata = routes.get_library().metadata
    foreign = Findings(Metadata(metadata.path, "other-workspace")).create(
        "Private", "answer", {"answer": "secret"}, saved=True
    )
    assert client.get(f"/api/v1/findings/{foreign['id']}").status_code == 404
    assert client.get(f"/api/v1/findings/{foreign['id']}/export").status_code == 404
    client.delete(f"/api/v1/documents/{jobs[0]['document_id']}")
    for format in ("json", "csv", "md"):
        assert (
            client.get(f"/api/v1/findings/{key}/export?format={format}").status_code
            == 409
        )
    assert client.get(f"/api/v1/findings/{key}").status_code == 409
    assert client.delete(f"/api/v1/findings/{key}").status_code == 200
