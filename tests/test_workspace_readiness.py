from test_phase4_api import client as client

from scripts.phase3_fixtures import create_pdf
from vision_rag.api import routes


def test_readiness_tracks_index_membership_revisions_and_deletion(client, tmp_path):
    library = routes.get_library()
    pdf = create_pdf(tmp_path / "report.pdf", ("text", "table"))

    def upload(name):
        return client.post(
            "/api/v1/ingest", files={"file": (name, pdf.read_bytes())}
        ).json()

    def documents():
        response = client.get("/api/v1/workspace/readiness")
        assert response.status_code == 200
        return {d["id"]: d for d in response.json()["documents"]}

    first = upload("first.pdf")
    assert documents()[first["document_id"]]["search_state"] == "reading"
    library.process_one()
    assert documents()[first["document_id"]]["search_state"] == "preparing"
    library.retrieval.queue()
    library.process_one()
    assert documents()[first["document_id"]]["search_state"] == "ready"

    second_pdf = create_pdf(tmp_path / "second.pdf", ("table",))
    second = client.post(
        "/api/v1/ingest", files={"file": ("second.pdf", second_pdf.read_bytes())}
    ).json()
    library.process_one()
    states = documents()
    assert states[first["document_id"]]["search_state"] == "ready"
    assert states[second["document_id"]]["search_state"] == "preparing"

    # Invalidating one page must remove the ready label even if others remain eligible.
    with library.metadata.connection(True) as db:
        db.execute(
            "UPDATE page_processing SET revision=revision+1 WHERE build_id IN "
            "(SELECT id FROM builds WHERE version_id=?) AND page_number=1",
            (first["version_id"],),
        )
    assert documents()[first["document_id"]]["search_state"] == "preparing"
    library.retrieval.queue()
    library.process_one()
    assert all(d["search_state"] == "ready" for d in documents().values())
    client.delete(f"/api/v1/documents/{first['document_id']}")
    assert first["document_id"] not in documents()
