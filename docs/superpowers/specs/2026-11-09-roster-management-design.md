# Roster management: invitations, validation, captain actions

Date: 2026-11-09. Branch: `roster-management`.

## Goal

Captains build and manage their rosters inside Hokie Rec instead of group chats, and the database and API reject roster states the Phase II/III requirements forbid.

Sources: Phase II requirements (privileges for Player and Team Captain, problem definition) and Phase III design (RosterMembership states, captain trigger, re-invite rule).

## Confirmed requirements

From the Phase II/III docs:
- R1. A captain registers a team only while the league's registration window is open.
- R2. A captain sends roster invitations and removes members, only for the team they captain.
- R3. A player accepts or declines invitations sent to them.
- R4. A player leaves a roster only before the league's roster lock date.
- R5. A captain hands off captaincy to another active member, and must do so before leaving.
- R6. Every team's captain has an active RosterMembership row on that team, checked at the end of the transaction, enforced by a trigger.
- R7. A player can't be on two rosters in the same league.
- R8. Membership moves from `invited` to `active`, `declined`, `removed` or `left`.
- R9. Re-inviting a former member updates their existing row (UNIQUE(team_id, user_id) stays).

Agreed with the user in this design session:
- R10. Captains invite by the player's VT PID. No user search.
- R11. `max_roster_size` counts active members only. Captains may over-invite; accepting fails once the team is full.
- R12. Invite-time eligibility: the captain learns at once if the PID is unknown, not an active player, suspended (never the suspension end date), already invited or active on this team, or already active on another team in this league.
- R13. Accepting an invite auto-declines the player's other pending invites in the same league.
- R14. Players see all their pending invites in one panel on the Teams page.
- R15. Roster changes (invite, accept, remove, leave) are blocked from the roster lock date on. Decline and withdraw are always allowed.
- R16. `min_roster_size` is shown, not enforced.

## Design

### Where rules live (hybrid)

| Rule | Enforced by |
|---|---|
| R6 captain is an active member | Deferred constraint trigger (fires at commit) |
| R7 one active roster per league | Constraint trigger on RosterMembership; locks the player's Users row so concurrent accepts serialize |
| R1, R11, R12, R15, role/suspension | FastAPI endpoint checks inside the same transaction |

Triggers raise SQLSTATE `23514` (check_violation) with `CONSTRAINT` set to `team_captain_on_roster` or `roster_one_team_per_league`. psycopg maps 23514 to IntegrityError, so the existing `integrity_error` handler and `FRIENDLY_ERRORS` produce the 409 message. The API pre-checks R7 too, for a clear message; the trigger is the backstop for races and non-API writes.

Capacity races (two players accepting the last spot) are serialized by `SELECT ... FROM Team WHERE team_id = %s FOR UPDATE` before counting active members.

### "Before the lock date"

`(NOW() AT TIME ZONE 'America/New_York')::date < roster_lock_date`. On the lock date itself the roster is locked. The registration window compares `NOW()` with the `timestamptz` columns directly.

### SQL files

- `db/schema.sql`: base tables only (the pasted copy of the auth tables is removed; audit finding 3).
- `db/auth.sql`: unchanged.
- `db/roster.sql` (new, rerunnable): the two trigger functions and triggers (`CREATE OR REPLACE FUNCTION`, `DROP TRIGGER IF EXISTS` then `CREATE CONSTRAINT TRIGGER`).
- `compose.yaml` mounts them as `01_schema.sql`, `02_auth.sql`, `03_roster.sql`.
- `backend/migrate_auth.py` is renamed `backend/migrate.py` and applies `auth.sql` then `roster.sql`. Tests load all three files.

The captain trigger checks the team of the changed row: on Team INSERT/UPDATE of `captain_id`, and on RosterMembership UPDATE/DELETE. It skips teams that no longer exist, so `DELETE FROM Team` (which cascades roster rows) still works.

Existing seed data passes both rules (checked 2026-11-09: 0 captains without an active row, 0 players active twice in one league).

### API

All write endpoints require sign-in (`AuthenticatedUser`) and keep the existing CSRF middleware.

| Endpoint | Caller | Behaviour |
|---|---|---|
| `POST /api/teams` | active, non-suspended player | Existing, plus R1 and R7 checks |
| `POST /api/teams/{id}/invites` `{vt_pid}` | captain | R15, R12. New row `invited`, or an existing `declined`/`removed`/`left` row reset to `invited` with `invited_at = NOW()`; `joined_at`/`left_at` keep the previous stint (R9). 201 → roster entry |
| `DELETE /api/teams/{id}/invites/{player_id}` | captain | Existing. Deletes the row only if `joined_at IS NULL`; a former member's withdrawn re-invite becomes `removed`, keeping `joined_at`/`left_at`. Takes the Team row lock, like accept. Allowed any time |
| `GET /api/me/invites` | signed-in user | Own pending invites: team, league, captain name, `roster_lock_date`, active count, `max_roster_size` |
| `POST /api/teams/{id}/invite/accept` | the invitee | R15, team not full (R11), invitee still eligible (R12), then `active`, `joined_at = NOW()`, `left_at = NULL` (only while still `invited`), and R13 |
| `POST /api/teams/{id}/invite/decline` | the invitee | `declined`. Allowed any time |
| `DELETE /api/teams/{id}/members/{player_id}` | captain | R15. Active non-captain only → `removed`, `left_at = NOW()` |
| `POST /api/teams/{id}/leave` | active member who isn't captain | R4/R15 → `left`, `left_at = NOW()`. Captain gets 409 "Hand off captaincy first." |
| `PUT /api/teams/{id}/captain` `{user_id}` | captain | Target must be an active member of this team. Allowed any time (roster membership doesn't change) |
| `GET /api/teams/{id}` | anyone | Existing, plus `roster_lock_date`, `min_roster_size`, `max_roster_size`, `roster_locked` |

Errors use the existing `{"detail": "..."}` shape: 401 not signed in, 403 not the captain or not the invitee, 404 unknown team, PID or invite, 409 rule broken with the reason, 422 bad input. Every authorization check runs before any data is changed or returned.

### Frontend

- `Teams.tsx`: "Your invitations" panel when signed in and `GET /api/me/invites` is non-empty, with Accept/Decline; reloads invites and the team list after each action.
- `TeamDetail.tsx`:
  - meta list adds "Roster N / max" and "Roster locks <date>" or "Roster locked";
  - captain panel: existing rename, plus an invite-by-PID form and a hand-off select with confirm;
  - roster rows: Remove on active non-captain members, Withdraw on invites (existing);
  - Leave team for an active non-captain member (confirm);
  - Accept/Decline banner when the signed-in user has a pending invite to this team;
  - roster-changing buttons disabled when `roster_locked`, with a note.
- `api.ts`: extend `Team` with the new fields; add an `Invite` type.

### Testing

Backend, in `backend/test_main.py` style (disposable schema, TestClient, CSRF header):
- success path of each new endpoint;
- 401 anonymous on every new write; 403 non-captain on invite, remove, hand-off, withdraw; 404 on accept/decline for a caller with no pending invite (these routes act on the caller's own row, so a non-invitee simply has none);
- registration closed, roster locked, team full, already active in the league (invite and accept), suspended invitee, unknown PID, captain remove/leave refused;
- triggers via raw SQL: setting the captain's row to `left` fails at commit; a second active roster in one league fails;
- re-invite reuses the row; withdrawn re-invite keeps history; accept auto-declines other invites in the league; two concurrent accepts for the last spot yield one 200 and one 409;
- all existing tests still pass, with fixtures moved inside the registration window where they register teams.

Frontend: `tsc -b`, `oxlint`, manual run in the browser pane with two demo accounts. No frontend test framework is added.

Docs: README API table rewritten (audit finding 2) and setup steps updated for `migrate.py`.

## Open decisions

- Open decision: how should the demo work on dates when every seeded league is closed? On 2026-11-09 Fall 2026 is past its lock date (Aug 29) and Spring 2027 registration opens 2026-12-01, so with these rules nothing can be registered or changed in the seeded data until Dec 1. Options: (a) shift `seed.sql` dates (shared change, affects the whole team), (b) a dev-only "current date" override (new config), (c) document a one-line SQL to open a Spring league locally. Interim behavior: rules are enforced exactly as written; the README documents option (c) for local demos; no shared data changes.
- Open decision: may an administrator reassign a captain (Phase II admin privilege)? Options: add an admin path to the hand-off endpoint now, or later with the admin UI. Interim behavior: only the current captain may hand off; no admin path.

- Open decision: what history should a former member's withdrawn re-invite keep? Options: (a) mark it `removed` and keep the original `joined_at`/`left_at` dates, (b) add a column so the previous status (`left`, `removed`) can be restored, (c) keep stints as separate rows (changes the Phase III re-invite rule). Interim behavior: (a); the dates are preserved, the earlier status word becomes `removed`.

## Rulings (implementation choices)

- Ruling: hybrid enforcement as tabled above.
- Ruling: hand-off is allowed after the lock date because the roster doesn't change.
- Ruling: a re-invite keeps `joined_at` from the previous stint until the player accepts again; `joined_at IS NULL` therefore means "never played for this team".
- Ruling: rename `migrate_auth.py` to `migrate.py` since it now applies two files.

## Out of scope

Admin roster tools, captain eligibility screen beyond invite-time checks, notifications, waivers, captain game confirmation, min-roster enforcement.
