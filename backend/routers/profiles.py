"""Private profile viewing and editing for the signed-in account."""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from psycopg.errors import UniqueViolation

from account_details import Email, Name, Phone
from routers.auth import AuthenticatedUser, User
from database import db

router = APIRouter(prefix="/api/me", tags=["Profile"])
PROFILE_COLUMNS = "user_id, vt_pid, first_name, last_name, email, phone, role, created_at"


class ProfileDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: Name
    last_name: Name
    email: Email
    phone: Phone | None


class Profile(User):
    vt_pid: str
    email: str
    phone: str | None
    created_at: datetime


@router.get("/profile", response_model=Profile)
def get_profile(user: AuthenticatedUser):
    with db() as conn:
        profile = conn.execute(f"SELECT {PROFILE_COLUMNS} FROM Users WHERE user_id = %s AND is_active",
                               (user["user_id"],)).fetchone()
    if profile is None:
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    return profile


@router.put("/profile", response_model=Profile)
def update_profile(body: ProfileDetails, user: AuthenticatedUser):
    try:
        with db() as conn:
            profile = conn.execute(f"""
                UPDATE Users SET first_name = %s, last_name = %s, email = %s, phone = %s
                WHERE user_id = %s AND is_active RETURNING {PROFILE_COLUMNS}
            """, (body.first_name, body.last_name, body.email, body.phone, user["user_id"])).fetchone()
    except UniqueViolation:
        raise HTTPException(409, "That email is already registered. Use a different email address.") from None
    if profile is None:
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    return profile
