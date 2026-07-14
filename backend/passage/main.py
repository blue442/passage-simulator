from fastapi import FastAPI

from passage import __version__
from passage.api.routes import router as api_router


def create_app() -> FastAPI:
    app = FastAPI(title="Passage Simulator")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(api_router)

    return app


app = create_app()
