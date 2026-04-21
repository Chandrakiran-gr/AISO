from fastapi import APIRouter
from datetime import datetime, timezone

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Simple ping endpoint — used by uptime monitors."""
    return {
        "status": "ok",
        "service": "aiso-api",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
