from pydantic import SecretStr
from test_phase4_api import client as client

from vision_rag.api import security
from vision_rag.config import settings


def test_project_page_is_separate_from_workspace_and_versions_its_assets(client):
    home = client.get("/")
    assert home.status_code == 200
    assert 'href="/workspace"' in home.text
    assert "/static/landing.css?v=" in home.text
    assert "/static/landing.js?v=" in home.text
    assert "/static/wireframe.css?v=" in home.text
    assert "/static/wireframe.js?v=" in home.text
    assert "/static/charcoal.css?v=" in home.text
    assert "/static/hero-simulation.css?v=" in home.text
    assert "/static/hero-simulation.js?v=" in home.text
    assert 'id="hero-simulation"' in home.text
    assert 'class="hero-orbit hero-orbit-left"' in home.text
    assert 'class="hero-orbit hero-orbit-right"' in home.text
    assert 'class="hero-sim-content"' not in home.text
    assert 'id="vision-wireframe"' in home.text
    assert (
        home.text.index('id="product"')
        < home.text.index('id="architecture"')
        < home.text.index('id="how-it-works"')
    )
    assert "/static/session.js" not in home.text
    assert 'id="chat-input"' not in home.text
    assert 'id="features"' in home.text
    assert 'id="architecture"' in home.text
    assert 'id="documentation"' in home.text
    workspace = client.get("/workspace")
    assert workspace.status_code == 200
    assert 'id="chat-input"' in workspace.text
    assert "/static/workspace.css?v=" in workspace.text
    assert "/static/emerald.css?v=" in workspace.text
    assert "/static/charcoal.css?v=" in workspace.text
    assert "/static/dashboard.js?v=" in workspace.text
    assert "/static/chat-studio.css?v=" in workspace.text
    assert 'aria-label="Home — About Vision"' in workspace.text
    assert 'id="expand-evidence"' in workspace.text
    assert 'id="viewer-fit-page"' in workspace.text
    assert 'id="viewer-fit-width"' in workspace.text
    assert 'class="chat-rail"' in workspace.text
    assert 'class="chat-workbench"' in workspace.text
    assert home.headers["cache-control"] == "no-store"
    assert client.get("/static/landing.css").status_code == 200
    assert client.get("/static/landing.js").status_code == 200
    assert client.get("/static/wireframe.css").status_code == 200
    assert client.get("/static/wireframe.js").status_code == 200
    assert client.get("/static/charcoal.css").status_code == 200
    assert client.get("/static/dashboard.js").status_code == 200
    assert client.get("/static/chat-studio.css").status_code == 200
    assert client.get("/static/hero-simulation.css").status_code == 200
    assert client.get("/static/hero-simulation.js").status_code == 200


def test_public_landing_does_not_open_owner_data(client, monkeypatch):
    monkeypatch.setattr(settings, "access_token", SecretStr("test-owner-" + "x" * 40))
    security.clear_sessions()
    assert client.get("/").status_code == 200
    assert client.get("/workspace").status_code == 200  # Public sign-in shell only.
    assert client.get("/api/v1/documents").status_code == 401
    assert client.get("/api/v1/workspace/readiness").status_code == 401
