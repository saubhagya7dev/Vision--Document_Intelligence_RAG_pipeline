"""Disposable failed-stream -> explicit non-streamed retry UI fixture."""

import browser_ux_fixture as fixture

from vision_rag.generate.provider_errors import ProviderFailure


class Provider(fixture.Provider):
    def generate_grounded_stream(self, query, evidence, images, delta, cancelled):
        delta("Unvalidated draft that must be discarded")
        raise ProviderFailure(
            503,
            "The answer provider is temporarily unavailable. Retry without streaming.",
        )


if __name__ == "__main__":
    fixture.Provider = Provider
    run = fixture.uvicorn.run

    def isolated(app, **kwargs):
        kwargs.update(port=18009, access_log=False)
        run(app, **kwargs)

    fixture.uvicorn.run = isolated
    fixture.main()
