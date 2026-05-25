from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ApiUser

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

@router.post("/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    OAuth2-compatible token login.
    Authenticate a user using their username and password (which is their API Token).
    Returns a standard access token required for accessing other endpoints.
    """
    user = db.query(ApiUser).filter(
        ApiUser.username == form_data.username,
        ApiUser.token == form_data.password
    ).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    return {
        "access_token": user.token,
        "token_type": "bearer"
    }
