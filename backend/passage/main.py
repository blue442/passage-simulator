from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse

from passage import __version__
from passage.api.routes import router as api_router
from passage.config import Settings, get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="Passage Simulator")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(api_router)

    @app.get("/{full_path:path}")
    def serve_frontend(
        full_path: str,
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> FileResponse:
        if settings.static_dir is None:
            raise HTTPException(status_code=404)

        candidate = settings.static_dir / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)

        return FileResponse(settings.static_dir / "index.html")

    return app


app = create_app()
