from fastapi import Header, HTTPException
from typing import Optional

def get_current_user_id(x_user_id: Optional[str] = Header(None)) -> str:
    """
    Dependency that extracts the authenticated user ID from the X-User-Id header.
    This header is securely set by the Next.js frontend proxy after verifying the NextAuth session.
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Unauthorized — missing X-User-Id header")
    return x_user_id
