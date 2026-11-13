import psycopg

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import os
from contextlib import asynccontextmanager

from database import db
from routers import (
    admin, assignments, auth, games, incidents, leagues,
    playoffs, players, profiles, reports, scores, teams,
)


@asynccontextmanager
async def lifespan(app):
    info = health()
    print(f"Connected to {info['version'].split(' on ')[0]} (database: {info['database']}), "
          f"{info['leagues']} leagues, {info['teams']} teams")
    yield


app = FastAPI(lifespan=lifespan)
for route_module in (
    auth, admin, incidents, scores, profiles, playoffs,
    leagues, teams, games, assignments, players, reports,
):
    app.include_router(route_module.router)

ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",") if origin.strip()]


@app.middleware("http")
async def protect_browser_requests(request: Request, call_next):
    # A custom header forces cross-origin browser writes through CORS preflight.
    # Check Origin too: SameSite alone does not protect against sibling origins.
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if request.headers.get("x-requested-with") != "HokieRec" or (origin is not None and origin not in ALLOWED_ORIGINS):
            return JSONResponse(status_code=403, content={"detail": "Request could not be verified. Refresh the page and try again."})
    response = await call_next(request)
    if request.url.path.startswith("/api/auth/") or request.url.path.endswith("/eligibility") or request.url.path in ("/api/me/profile", "/api/me/teams", "/api/me/games", "/api/me/membership-history"):
        response.headers["Cache-Control"] = "no-store"
    return response


# Allow requests from the React development server
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRIENDLY_ERRORS = {
    "team_league_id_team_name_key": "A team with that name already exists in this league.",
    "team_league_id_fkey": "That league does not exist.",
    # Game and ScoreReport reference Team with ON DELETE RESTRICT
    "game_home_team_id_fkey": "This team has games on the schedule or in the results, so it can't be deleted.",
    "game_away_team_id_fkey": "This team has games on the schedule or in the results, so it can't be deleted.",
    "scorereport_forfeit_team_id_fkey": "This team has score reports on record, so it can't be deleted.",
    # Raised by the triggers in db/roster.sql
    "team_captain_on_roster": "A team's captain must be an active member of its roster.",
    "roster_one_team_per_league": "A player can be on only one team per league.",
}


@app.exception_handler(psycopg.errors.IntegrityError)
def integrity_error(request, e):
    message = FRIENDLY_ERRORS.get(e.diag.constraint_name, e.diag.message_primary)
    return JSONResponse(status_code=409, content={"detail": message})


@app.exception_handler(psycopg.DataError)
def data_error(request, e):
    # Bad values pydantic can't catch (NUL bytes, out-of-range ids); some are raised client-side with no diag
    return JSONResponse(status_code=422, content={"detail": e.diag.message_primary or str(e)})


@app.get("/api/health")
def health():
    with db() as conn:
        row = conn.execute("""
            SELECT version() AS version, current_database() AS database,
                   (SELECT COUNT(*) FROM League) AS leagues, (SELECT COUNT(*) FROM Team) AS teams
        """).fetchone()
    return {"status": "connected", **row}


