"""Disposable owner sign-in fixture, using only fictional Phase 6 reports."""

import browser_phase6_fixture as fixture
from pydantic import SecretStr

from vision_rag.config import settings

if __name__ == "__main__":
    settings.access_token = SecretStr("public-fixture-only-token-1234567890")
    settings.deployment_profile = "authenticated"
    run = fixture.uvicorn.run

    def isolated(app, **kwargs):
        kwargs.update(port=18007, access_log=False)
        run(app, **kwargs)

    fixture.uvicorn.run = isolated
    fixture.main()
