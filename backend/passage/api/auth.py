import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from passage.config import Settings, get_settings

bearer_scheme = HTTPBearer(auto_error=False)


def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if credentials is None or not secrets.compare_digest(credentials.credentials, settings.auth_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
