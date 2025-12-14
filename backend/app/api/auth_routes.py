from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List

from app.core.database import get_db
from app.models.models import User, Household
from app.services import auth

router = APIRouter(prefix="/auth", tags=["auth"])


# ============ Pydantic Schemas ============

class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    household_name: Optional[str] = None  # For creating new household
    invite_code: Optional[str] = None  # For joining existing household


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    display_name: Optional[str]
    household_id: int
    household_name: str
    is_admin: bool
    daily_calorie_target: int = 1800

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    token: str
    user: UserResponse


class CalorieTargetUpdate(BaseModel):
    daily_calorie_target: int


# ============ Auth Endpoints ============

@router.post("/register", response_model=TokenResponse)
async def register(data: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user - requires invite code to join existing household"""
    
    # Check if username already exists
    existing = db.query(User).filter(User.username == data.username.lower()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Benutzername bereits vergeben")
    
    # Require invite code - no public registration
    if not data.invite_code:
        raise HTTPException(status_code=400, detail="Einladungscode erforderlich")
    
    # Join existing household
    household = auth.get_household_by_invite_code(db, data.invite_code)
    if not household:
        raise HTTPException(status_code=400, detail="Ungültiger Einladungscode")
    
    # Create user
    user = auth.create_user(
        db=db,
        username=data.username,
        password=data.password,
        household_id=household.id,
        display_name=data.display_name,
        is_admin=False  # Only first user (created via DB) is admin
    )
    
    # Create token
    token = auth.create_access_token(user.id, household.id)
    
    return TokenResponse(
        token=token,
        user=UserResponse(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            household_id=household.id,
            household_name=household.name,
            is_admin=user.is_admin,
            daily_calorie_target=user.daily_calorie_target or 1800
        )
    )


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: Session = Depends(get_db)):
    """Login with username and password"""
    
    user = auth.authenticate_user(db, data.username, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Ungültiger Benutzername oder Passwort")
    
    household = db.query(Household).filter(Household.id == user.household_id).first()
    
    # Create token
    token = auth.create_access_token(user.id, user.household_id)
    
    return TokenResponse(
        token=token,
        user=UserResponse(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            household_id=user.household_id,
            household_name=household.name if household else "Unknown",
            is_admin=user.is_admin,
            daily_calorie_target=user.daily_calorie_target or 1800
        )
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Get current logged in user"""
    
    # Get token from header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    
    token = auth_header.replace("Bearer ", "")
    payload = auth.decode_token(token)
    
    if not payload:
        raise HTTPException(status_code=401, detail="Ungültiger oder abgelaufener Token")
    
    user = auth.get_user_by_id(db, payload["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="Benutzer nicht gefunden")
    
    household = db.query(Household).filter(Household.id == user.household_id).first()
    
    return UserResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        household_id=user.household_id,
        household_name=household.name if household else "Unknown",
        is_admin=user.is_admin,
        daily_calorie_target=user.daily_calorie_target or 1800
    )


@router.put("/me/calories", response_model=UserResponse)
async def update_calorie_target(data: CalorieTargetUpdate, request: Request, db: Session = Depends(get_db)):
    """Update user's daily calorie target"""
    
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    
    token = auth_header.replace("Bearer ", "")
    payload = auth.decode_token(token)
    
    if not payload:
        raise HTTPException(status_code=401, detail="Ungültiger Token")
    
    user = auth.get_user_by_id(db, payload["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="Benutzer nicht gefunden")
    
    # Update calorie target
    user.daily_calorie_target = data.daily_calorie_target
    db.commit()
    db.refresh(user)
    
    household = db.query(Household).filter(Household.id == user.household_id).first()
    
    return UserResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        household_id=user.household_id,
        household_name=household.name if household else "Unknown",
        is_admin=user.is_admin,
        daily_calorie_target=user.daily_calorie_target or 1800
    )


@router.get("/household")
async def get_household_info(request: Request, db: Session = Depends(get_db)):
    """Get household info including invite code (admin only)"""
    
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    
    token = auth_header.replace("Bearer ", "")
    payload = auth.decode_token(token)
    
    if not payload:
        raise HTTPException(status_code=401, detail="Ungültiger Token")
    
    user = auth.get_user_by_id(db, payload["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="Benutzer nicht gefunden")
    
    household = db.query(Household).filter(Household.id == user.household_id).first()
    
    # Get all users in household
    users = db.query(User).filter(User.household_id == household.id).all()
    
    # Parse preferred supermarkets
    supermarkets = household.preferred_supermarkets.split(",") if household.preferred_supermarkets else []
    
    return {
        "id": household.id,
        "name": household.name,
        "postal_code": household.postal_code,
        "preferred_supermarkets": supermarkets,
        "invite_code": household.invite_code if user.is_admin else None,
        "members": [
            {"id": u.id, "username": u.username, "display_name": u.display_name, "is_admin": u.is_admin}
            for u in users
        ]
    }


class HouseholdUpdate(BaseModel):
    postal_code: Optional[str] = None
    preferred_supermarkets: Optional[List[str]] = None


@router.put("/household")
async def update_household(data: HouseholdUpdate, request: Request, db: Session = Depends(get_db)):
    """Update household settings (admin only)"""
    
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    
    token = auth_header.replace("Bearer ", "")
    payload = auth.decode_token(token)
    
    if not payload:
        raise HTTPException(status_code=401, detail="Ungültiger Token")
    
    user = auth.get_user_by_id(db, payload["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="Benutzer nicht gefunden")
    
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Nur Admins können Haushalt-Einstellungen ändern")
    
    household = db.query(Household).filter(Household.id == user.household_id).first()
    
    if data.postal_code is not None:
        household.postal_code = data.postal_code
    
    if data.preferred_supermarkets is not None:
        household.preferred_supermarkets = ",".join(data.preferred_supermarkets)
    
    db.commit()
    db.refresh(household)
    
    supermarkets = household.preferred_supermarkets.split(",") if household.preferred_supermarkets else []
    
    return {"status": "updated", "postal_code": household.postal_code, "preferred_supermarkets": supermarkets}
