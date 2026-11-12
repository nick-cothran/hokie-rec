"""Administrator-only account management."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from psycopg.errors import UniqueViolation

from auth import SignUp, User, create_account, current_user
from database import db

router = APIRouter(prefix="/api/admin", tags=["Administration"])


def require_admin(user: Annotated[dict, Depends(current_user)]) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Only administrators can manage accounts.")
    return user


Admin = Annotated[dict, Depends(require_admin)]


class NewAccount(SignUp):
    # Same validation as sign-up, plus the role an administrator chooses
    role: Literal["player", "official", "admin"]


@router.get("/users")
def list_users(admin: Admin):
    with db() as conn:
        return conn.execute("""
            SELECT user_id, vt_pid, first_name, last_name, email, role, is_active, created_at
            FROM Users ORDER BY last_name, first_name, user_id
        """).fetchall()


@router.post("/users", response_model=User, status_code=201)
def create_user(body: NewAccount, admin: Admin):
    # The administrator stays signed in as themselves; the new person signs in with
    # the initial password and can change it from their account page.
    try:
        with db() as conn:
            return create_account(conn, body, body.role)
    except UniqueViolation:
        raise HTTPException(409, "That PID or email is already registered.") from None
