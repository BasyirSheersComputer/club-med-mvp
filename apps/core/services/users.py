"""
User Authentication Service for Phase 4
========================================

Handles:
- Password hashing with bcrypt
- User creation and validation
- Login/logout with audit
- Account lockout after failed attempts
"""
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

# Use SHA256 for password hashing (in production use bcrypt/argon2)
# Note: For proper security, add bcrypt to requirements and use that
HASH_ITERATIONS = 100000
PASSWORD_SALT = os.getenv("PASSWORD_SALT", secrets.token_hex(16))

# Account lockout settings
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15


# ============================================================================
# PASSWORD HASHING
# ============================================================================

def hash_password(password: str, salt: str = None) -> str:
    """
    Hash a password using PBKDF2-SHA256.
    
    In production, use bcrypt or argon2id instead.
    """
    salt = salt or PASSWORD_SALT
    
    # PBKDF2 with SHA256
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        HASH_ITERATIONS
    )
    
    return key.hex()


def verify_password(password: str, hashed: str, salt: str = None) -> bool:
    """Verify a password against its hash."""
    return hash_password(password, salt) == hashed


# ============================================================================
# USER MANAGEMENT
# ============================================================================

def create_user(
    email: str,
    password: str,
    name: str,
    role: str = "front_desk_agent",
    resort_id: str = None,
    db = None,
    created_by: str = None
) -> Dict[str, Any]:
    """
    Create a new user with hashed password.
    """
    from models import UserModel
    
    if not db:
        return {"error": "Database session required"}
    
    # Check if email already exists
    existing = db.query(UserModel).filter(UserModel.email == email).first()
    if existing:
        return {"error": "Email already registered"}
    
    # Validate role
    valid_roles = ["super_admin", "resort_manager", "front_desk_agent", "readonly"]
    if role not in valid_roles:
        return {"error": f"Invalid role. Must be one of: {valid_roles}"}
    
    # Create user
    user = UserModel(
        email=email,
        hashed_password=hash_password(password),
        name=name,
        role=role,
        resort_id=resort_id,
        created_by=created_by,
        is_active=True
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    print(f"👤 User created: {email} (role: {role})")
    
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "resort_id": user.resort_id,
        "created_at": user.created_at.isoformat()
    }


def authenticate_user(email: str, password: str, db) -> Dict[str, Any]:
    """
    Authenticate a user with email and password.
    
    Implements account lockout after failed attempts.
    """
    from models import UserModel
    
    user = db.query(UserModel).filter(UserModel.email == email).first()
    
    if not user:
        return {"error": "Invalid credentials", "authenticated": False}
    
    # Check account status
    if not user.is_active:
        return {"error": "Account is deactivated", "authenticated": False}
    
    # Check lockout
    if user.locked_until and user.locked_until > datetime.utcnow():
        remaining = (user.locked_until - datetime.utcnow()).seconds // 60
        return {
            "error": f"Account locked. Try again in {remaining} minutes",
            "authenticated": False,
            "locked": True
        }
    
    # Verify password
    if not verify_password(password, user.hashed_password):
        # Increment failed attempts
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        
        if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            print(f"🔒 Account locked: {email}")
        
        db.commit()
        
        remaining_attempts = MAX_FAILED_ATTEMPTS - user.failed_login_attempts
        return {
            "error": "Invalid credentials",
            "authenticated": False,
            "attempts_remaining": max(0, remaining_attempts)
        }
    
    # Successful login
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.utcnow()
    db.commit()
    
    print(f"✅ User authenticated: {email}")
    
    return {
        "authenticated": True,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "resort_id": user.resort_id
        }
    }


def change_password(
    user_id: str,
    current_password: str,
    new_password: str,
    db
) -> Dict[str, Any]:
    """
    Change a user's password.
    """
    from models import UserModel
    
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    
    if not user:
        return {"error": "User not found"}
    
    if not verify_password(current_password, user.hashed_password):
        return {"error": "Current password is incorrect"}
    
    user.hashed_password = hash_password(new_password)
    user.password_changed_at = datetime.utcnow()
    db.commit()
    
    print(f"🔑 Password changed: {user.email}")
    
    return {"success": True, "message": "Password changed successfully"}


def reset_password(user_id: str, new_password: str, db) -> Dict[str, Any]:
    """
    Admin password reset (no current password required).
    """
    from models import UserModel
    
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    
    if not user:
        return {"error": "User not found"}
    
    user.hashed_password = hash_password(new_password)
    user.password_changed_at = datetime.utcnow()
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
    
    print(f"🔑 Password reset by admin: {user.email}")
    
    return {"success": True, "message": "Password reset successfully"}


def deactivate_user(user_id: str, db) -> Dict[str, Any]:
    """Deactivate a user account."""
    from models import UserModel
    
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    
    if not user:
        return {"error": "User not found"}
    
    user.is_active = False
    db.commit()
    
    print(f"❌ User deactivated: {user.email}")
    
    return {"success": True, "message": "User deactivated"}


def list_users(db, resort_id: str = None) -> list:
    """List all users, optionally filtered by resort."""
    from models import UserModel
    
    query = db.query(UserModel)
    
    if resort_id:
        query = query.filter(UserModel.resort_id == resort_id)
    
    users = query.all()
    
    return [
        {
            "id": u.id,
            "email": u.email,
            "name": u.name,
            "role": u.role,
            "resort_id": u.resort_id,
            "is_active": u.is_active,
            "last_login": u.last_login.isoformat() if u.last_login else None,
            "created_at": u.created_at.isoformat() if u.created_at else None
        }
        for u in users
    ]
