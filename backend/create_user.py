#!/usr/bin/env python3
"""Create initial admin user for Food Planer"""

import sys
import os

# Add backend to path
sys.path.insert(0, '/app')

from app.services.auth import hash_password
from app.core.database import SessionLocal
from app.models.models import User

def create_admin_user(username: str, password: str, display_name: str = None):
    db = SessionLocal()
    
    # Check if user exists
    existing = db.query(User).filter(User.username == username.lower()).first()
    if existing:
        print(f"User '{username}' already exists!")
        return
    
    user = User(
        username=username.lower(),
        password_hash=hash_password(password),
        display_name=display_name or username,
        household_id=1,
        is_admin=True
    )
    db.add(user)
    db.commit()
    print(f"Admin user '{username}' created successfully!")
    db.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python create_user.py <username> <password> [display_name]")
        sys.exit(1)
    
    username = sys.argv[1]
    password = sys.argv[2]
    display_name = sys.argv[3] if len(sys.argv) > 3 else None
    
    create_admin_user(username, password, display_name)
