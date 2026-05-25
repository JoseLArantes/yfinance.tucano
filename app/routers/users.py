import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ApiUser
from app.schemas import ApiUserCreate, ApiUserResponse

router = APIRouter(prefix="/api/v1/users", tags=["users"])

# Bearer security for creating users (global token style)
bearer_security = HTTPBearer(auto_error=False)

@router.post("", response_model=ApiUserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: ApiUserCreate,
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_security)
):
    """
    Create a new API User and return their generated API token.
    If no users exist in the database, this endpoint is public to bootstrap the service.
    Otherwise, a valid Bearer token from an existing user is required in the Authorization header.
    """
    user_count = db.query(ApiUser).count()
    if user_count > 0:
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization credentials (Bearer token) are required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = credentials.credentials
        current_user = db.query(ApiUser).filter(ApiUser.token == token).first()
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API Token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Check if username already exists
    existing_user = db.query(ApiUser).filter(ApiUser.username == payload.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered."
        )

    # Generate token if not provided
    token_value = payload.token or secrets.token_hex(24)

    new_user = ApiUser(
        username=payload.username,
        token=token_value
    )
    
    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return new_user
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create user: {str(e)}"
        )
