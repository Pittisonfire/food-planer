from datetime import datetime, timedelta
from typing import Optional
import hashlib
import secrets
import jwt
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.models import User, Household

settings = get_settings()


def hash_password(password: str) -> str:
    """Hash password with SHA256 + salt"""
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    return f"{salt}:{pwd_hash}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash"""
    try:
        salt, stored_hash = password_hash.split(":")
        pwd_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        return pwd_hash == stored_hash
    except:
        return False


def create_access_token(user_id: int, household_id: int) -> str:
    """Create JWT access token"""
    expire = datetime.utcnow() + timedelta(days=settings.jwt_expire_days)
    payload = {
        "user_id": user_id,
        "household_id": household_id,
        "exp": expire
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[dict]:
    """Decode and verify JWT token"""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def generate_invite_code() -> str:
    """Generate a unique invite code for household"""
    return secrets.token_urlsafe(8)[:10].upper()


def create_household(db: Session, name: str) -> Household:
    """Create a new household"""
    household = Household(
        name=name,
        invite_code=generate_invite_code()
    )
    db.add(household)
    db.commit()
    db.refresh(household)
    return household


def create_user(db: Session, username: str, password: str, household_id: int, display_name: str = None, is_admin: bool = False) -> User:
    """Create a new user"""
    user = User(
        username=username.lower(),
        password_hash=hash_password(password),
        display_name=display_name or username,
        household_id=household_id,
        is_admin=is_admin
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """Authenticate user with username and password"""
    user = db.query(User).filter(User.username == username.lower()).first()
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    """Get user by ID"""
    return db.query(User).filter(User.id == user_id).first()


def get_household_by_invite_code(db: Session, invite_code: str) -> Optional[Household]:
    """Get household by invite code"""
    return db.query(Household).filter(Household.invite_code == invite_code.upper()).first()
