import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from passage.config import Settings, get_settings
from passage.db import get_connection

bearer_scheme = HTTPBearer(auto_error=False)


def require_cron_secret(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if credentials is None or not secrets.compare_digest(credentials.credentials, settings.cron_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


router = APIRouter(prefix="/api/cron", dependencies=[Depends(require_cron_secret)])


@router.get("/keepalive")
def keepalive(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
    with get_connection(settings) as conn:
        with conn.cursor() as cursor:
            cursor.execute("select 1")

    return {"database": "ok"}
