"""Password authentication and revocable, fixed-lifetime server-side sessions."""

import hashlib
import os
import secrets
import re
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
from psycopg.errors import UniqueViolation
from pwdlib import PasswordHash

from database import db
from account_details import Email, Name, Phone

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
password_hasher = PasswordHash.recommended()
# Unknown accounts still perform an expensive verification to reduce timing leaks.
DUMMY_HASH = password_hasher.hash(secrets.token_urlsafe(32))
COOKIE_NAME = "hokie_rec_session"
COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
SESSION_LIFETIME = timedelta(hours=12)
LOGIN_LIMIT = 10


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Login(BaseModel):
    vt_pid: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")]
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class SignUp(Login):
    model_config = ConfigDict(extra="forbid")

    first_name: Name
    last_name: Name
    email: Email
    phone: Phone
    password: Annotated[str, StringConstraints(min_length=12, max_length=128)]

    @field_validator("vt_pid")
    @classmethod
    def normalize_pid(cls, value: str) -> str:
        pid = value.lower()
        if re.fullmatch(r"simvt\d+", pid):
            raise ValueError("This PID is reserved for a demo account. Sign in or choose another PID.")
        return pid


class User(BaseModel):
    user_id: int
    first_name: str
    last_name: str
    role: str


def current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE_NAME, "")
    if not token or len(token) > 128:
        raise HTTPException(401, "Please sign in to continue.")
    with db() as conn:
        user = conn.execute("""
            SELECT u.user_id, u.first_name, u.last_name, u.role
            FROM AuthSession s JOIN Users u ON u.user_id = s.user_id
            WHERE s.token_hash = %s AND s.expires_at > NOW() AND u.is_active
        """, (token_hash(token),)).fetchone()
    if user is None:
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    return user


AuthenticatedUser = Annotated[dict, Depends(current_user)]


def limit_attempts(identifier: str, limit: int, message: str):
    # Count attempts atomically and persist even if authentication fails. Hashing the
    # normalized PID bounds the key size and avoids storing submitted identifiers.
    with db() as conn:
        attempts = conn.execute("""
            INSERT INTO AuthLoginAttempt (identifier_hash, attempts, window_start)
            VALUES (%s, 1, NOW())
            ON CONFLICT (identifier_hash) DO UPDATE SET
                attempts = CASE WHEN AuthLoginAttempt.window_start < NOW() - INTERVAL '15 minutes'
                                THEN 1 ELSE LEAST(AuthLoginAttempt.attempts + 1, %s) END,
                window_start = CASE WHEN AuthLoginAttempt.window_start < NOW() - INTERVAL '15 minutes'
                                    THEN NOW() ELSE AuthLoginAttempt.window_start END
            RETURNING attempts
        """, (token_hash(identifier), limit + 1)).fetchone()["attempts"]
    if attempts > limit:
        raise HTTPException(429, message, headers={"Retry-After": "900"})


def issue_session(conn, user_id: int, request: Request) -> str:
    token = secrets.token_urlsafe(32)
    previous = request.cookies.get(COOKIE_NAME, "")
    if previous:
        conn.execute("DELETE FROM AuthSession WHERE token_hash = %s", (token_hash(previous),))
    conn.execute("DELETE FROM AuthSession WHERE expires_at <= NOW()")
    conn.execute("DELETE FROM AuthLoginAttempt WHERE window_start < NOW() - INTERVAL '15 minutes'")
    conn.execute("""
        INSERT INTO AuthSession (token_hash, user_id, expires_at)
        VALUES (%s, %s, NOW() + %s)
    """, (token_hash(token), user_id, SESSION_LIFETIME))
    return token


def set_session_cookie(response: Response, token: str):
    response.set_cookie(COOKIE_NAME, token, max_age=int(SESSION_LIFETIME.total_seconds()),
                        httponly=True, secure=COOKIE_SECURE, samesite="lax", path="/api")


def create_account(conn, details: SignUp, role: str) -> dict:
    """Insert the profile and its password hash; the caller's transaction commits both or neither."""
    account = conn.execute("""
        INSERT INTO Users (vt_pid, first_name, last_name, email, phone, role)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING user_id, first_name, last_name, role
    """, (details.vt_pid, details.first_name, details.last_name, details.email, details.phone, role)).fetchone()
    conn.execute("INSERT INTO UserCredentials (user_id, password_hash) VALUES (%s, %s)",
                 (account["user_id"], password_hasher.hash(details.password)))
    return account


@router.post("/sign-up", response_model=User, status_code=201)
def sign_up(body: SignUp, request: Request, response: Response):
    # Do not trust forwarded headers supplied by a caller. A new-account flood
    # must share a budget even when every attempted PID is different.
    host = request.client.host if request.client else "unknown"
    limit_attempts(f"signup:{host}", 10, "Too many account creation attempts. Try again in 15 minutes.")
    try:
        # Profile, credentials, and session succeed or roll back together. Never
        # attach a new password to an existing PID or accept a caller's role.
        with db() as conn:
            account = create_account(conn, body, "player")
            token = issue_session(conn, account["user_id"], request)
            conn.execute("DELETE FROM AuthLoginAttempt WHERE identifier_hash = %s", (token_hash(body.vt_pid),))
    except UniqueViolation:
        raise HTTPException(409, "That PID or email is already registered. Sign in or use different details.") from None
    set_session_cookie(response, token)
    return account


@router.post("/login", response_model=User)
def login(body: Login, request: Request, response: Response):
    pid = body.vt_pid.lower()
    limit_attempts(pid, LOGIN_LIMIT, "Too many sign-in attempts. Try again in 15 minutes.")

    with db() as conn:
        account = conn.execute("""
            SELECT u.user_id, u.first_name, u.last_name, u.role, u.is_active, c.password_hash
            FROM Users u JOIN UserCredentials c ON c.user_id = u.user_id
            WHERE LOWER(u.vt_pid) = %s
        """, (pid,)).fetchone()
    valid = password_hasher.verify(body.password, account["password_hash"] if account else DUMMY_HASH)
    if not valid or not account or not account["is_active"]:
        raise HTTPException(401, "Invalid PID or password.")

    with db() as conn:
        # Reauthentication rotates this browser's session rather than leaving it valid.
        token = issue_session(conn, account["user_id"], request)
        conn.execute("DELETE FROM AuthLoginAttempt WHERE identifier_hash = %s", (token_hash(pid),))
    set_session_cookie(response, token)
    return account


@router.get("/me", response_model=User)
def me(user: AuthenticatedUser):
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME, "")
    if token:
        with db() as conn:
            conn.execute("DELETE FROM AuthSession WHERE token_hash = %s", (token_hash(token),))
    response.delete_cookie(COOKIE_NAME, path="/api", httponly=True, secure=COOKIE_SECURE, samesite="lax")


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    new_password: Annotated[str, StringConstraints(min_length=12, max_length=128)]


class PasswordVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


def verify_current_password(user_id: int, current_password: str):
    limit_attempts(f"password:{user_id}", LOGIN_LIMIT, "Too many password attempts. Try again in 15 minutes.")
    with db() as conn:
        stored = conn.execute("SELECT password_hash FROM UserCredentials WHERE user_id = %s", (user_id,)).fetchone()
    if stored is None or not password_hasher.verify(current_password, stored["password_hash"]):
        raise HTTPException(400, "Your current password is incorrect.")


@router.post("/password/verify", status_code=204)
def verify_password(body: PasswordVerification, user: AuthenticatedUser):
    verify_current_password(user["user_id"], body.current_password)
    with db() as conn:
        conn.execute("DELETE FROM AuthLoginAttempt WHERE identifier_hash = %s",
                     (token_hash(f"password:{user['user_id']}"),))


@router.post("/password", status_code=204)
def change_password(body: PasswordChange, user: AuthenticatedUser, request: Request, response: Response):
    # A stolen session must not be able to guess the current password indefinitely.
    verify_current_password(user["user_id"], body.current_password)
    if body.new_password == body.current_password:
        raise HTTPException(400, "Choose a new password that is different from your current one.")

    with db() as conn:
        conn.execute("UPDATE UserCredentials SET password_hash = %s WHERE user_id = %s",
                     (password_hasher.hash(body.new_password), user["user_id"]))
        # Sign out every other browser, then give this one a fresh session.
        conn.execute("DELETE FROM AuthSession WHERE user_id = %s", (user["user_id"],))
        token = issue_session(conn, user["user_id"], request)
        conn.execute("DELETE FROM AuthLoginAttempt WHERE identifier_hash = %s",
                     (token_hash(f"password:{user['user_id']}"),))
    set_session_cookie(response, token)
