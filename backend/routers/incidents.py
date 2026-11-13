"""Incident reports filed by assigned officials and reviewed by administrators."""

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, StringConstraints

from routers.auth import AuthenticatedUser
from database import db

router = APIRouter(tags=["Incident reports"])

IncidentType = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
IncidentDescription = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
VtPid = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class NewIncidentReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_type: IncidentType
    description: IncidentDescription
    involved_user_pid: VtPid | None = None


class IncidentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["reviewed", "dismissed"]


INCIDENT_COLUMNS = """
    i.incident_id, i.game_id, l.league_id, l.league_name, g.start_time,
    g.facility_id, f.facility_name, f.location,
    g.home_team_id, h.team_name AS home_team_name,
    g.away_team_id, a.team_name AS away_team_name,
    i.incident_type, i.description, i.status, i.filed_at,
    i.filed_by, filer.first_name AS filed_by_first_name, filer.last_name AS filed_by_last_name,
    i.involved_user_id, involved.first_name AS involved_first_name, involved.last_name AS involved_last_name,
    i.reviewed_by, reviewer.first_name AS reviewed_by_first_name, reviewer.last_name AS reviewed_by_last_name
"""

INCIDENT_JOINS = """
    FROM IncidentReport i
    JOIN Game g ON g.game_id = i.game_id
    JOIN LeagueView l ON l.league_id = g.league_id
    JOIN Facility f ON f.facility_id = g.facility_id
    LEFT JOIN Team h ON h.team_id = g.home_team_id
    LEFT JOIN Team a ON a.team_id = g.away_team_id
    JOIN Users filer ON filer.user_id = i.filed_by
    LEFT JOIN Users involved ON involved.user_id = i.involved_user_id
    LEFT JOIN Users reviewer ON reviewer.user_id = i.reviewed_by
"""


@router.get("/api/incidents")
def list_incident_reports(response: Response, user: AuthenticatedUser):
    response.headers["Cache-Control"] = "no-store"
    if user["role"] not in ("official", "admin"):
        raise HTTPException(403, "Only officials and administrators can access incident reports.")
    with db() as conn:
        return conn.execute(f"""
            SELECT {INCIDENT_COLUMNS} {INCIDENT_JOINS}
            WHERE (%(is_admin)s OR i.filed_by = %(user_id)s)
            ORDER BY i.filed_at DESC, i.incident_id DESC
        """, {"is_admin": user["role"] == "admin", "user_id": user["user_id"]}).fetchall()


@router.post("/api/games/{game_id}/incident-reports", status_code=201)
def file_incident_report(game_id: int, body: NewIncidentReport, user: AuthenticatedUser):
    if user["role"] != "official":
        raise HTTPException(403, "Only an assigned official can file an incident report.")
    with db() as conn:
        game = conn.execute("""
            SELECT status FROM Game WHERE game_id = %s FOR UPDATE
        """, (game_id,)).fetchone()
        if game is None:
            raise HTTPException(404, "Game not found.")
        assignment = conn.execute("""
            SELECT status FROM OfficiatingAssignment
            WHERE game_id = %s AND official_id = %s FOR SHARE
        """, (game_id, user["user_id"])).fetchone()
        if assignment is None:
            raise HTTPException(403, "Only an official assigned to this game can file an incident report.")
        if assignment["status"] == "declined":
            raise HTTPException(403, "You declined this assignment and cannot file an incident report.")
        if game["status"] == "cancelled":
            raise HTTPException(409, "Cancelled games cannot receive incident reports.")

        involved_user_id = None
        if body.involved_user_pid:
            involved = conn.execute("""
                SELECT user_id FROM Users WHERE LOWER(vt_pid) = LOWER(%s)
            """, (body.involved_user_pid,)).fetchone()
            if involved is None:
                raise HTTPException(404, "No user with that PID.")
            involved_user_id = involved["user_id"]

        return conn.execute("""
            INSERT INTO IncidentReport
                (game_id, filed_by, involved_user_id, incident_type, description, status, filed_at)
            VALUES (%s, %s, %s, %s, %s, 'open', clock_timestamp())
            RETURNING incident_id, game_id, status, filed_at
        """, (game_id, user["user_id"], involved_user_id, body.incident_type, body.description)).fetchone()


@router.patch("/api/incidents/{incident_id}")
def decide_incident_report(incident_id: int, body: IncidentDecision, user: AuthenticatedUser):
    if user["role"] != "admin":
        raise HTTPException(403, "Only administrators can review incident reports.")
    with db() as conn:
        report = conn.execute("""
            UPDATE IncidentReport
            SET status = %s, reviewed_by = %s
            WHERE incident_id = %s AND status = 'open'
            RETURNING incident_id, status, reviewed_by
        """, (body.status, user["user_id"], incident_id)).fetchone()
        if report is not None:
            return report
        exists = conn.execute(
            "SELECT status FROM IncidentReport WHERE incident_id = %s", (incident_id,)
        ).fetchone()
    if exists is None:
        raise HTTPException(404, "Incident report not found.")
    raise HTTPException(409, "This incident report has already been resolved.")
