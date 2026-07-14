from fastapi import APIRouter, Depends

from passage.api.auth import require_auth

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


@router.get("/me")
def me() -> dict[str, bool]:
    return {"authenticated": True}
