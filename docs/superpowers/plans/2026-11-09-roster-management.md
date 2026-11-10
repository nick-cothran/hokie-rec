# Roster Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Captains invite players by PID, remove members and hand off captaincy; players accept, decline and leave; the API and two triggers enforce the league's roster rules.

**Architecture:** Hybrid. Two Postgres constraint triggers in a new `db/roster.sql` hold the invariants (captain on roster, one team per league). FastAPI endpoints in `backend/main.py` enforce date, capacity and eligibility rules inside one transaction with row locks. React pages `Teams.tsx` and `TeamDetail.tsx` get the matching controls.

**Tech Stack:** FastAPI, psycopg 3, PostgreSQL 17, unittest + TestClient, React 19 + TypeScript + Vite.

**Spec:** `docs/superpowers/specs/2026-11-09-roster-management-design.md`

## Global Constraints

- Local "today" is `(NOW() AT TIME ZONE 'America/New_York')::date`; a roster is locked when local today `>= roster_lock_date`.
- Registration is open when `NOW() BETWEEN reg_open_at AND reg_close_at`.
- `max_roster_size` counts `status = 'active'` rows only.
- Statuses: `invited`, `active`, `declined`, `removed`, `left`. No others.
- Every write endpoint takes `user: AuthenticatedUser` and checks authorization before reading or changing protected rows.
- Errors are `HTTPException(status, "<message>")`; 409 for a rule, 403 not allowed, 404 not found.
- Trigger errors: `RAISE EXCEPTION ... USING ERRCODE = 'check_violation', CONSTRAINT = '<name>'` and a `FRIENDLY_ERRORS` entry.
- Date text in messages: `f"{d:%b} {d.day}, {d.year}"` (no `%-d`; teammates run Windows).
- No new dependencies.

## Review Focus

1. Two players accepting the last open spot at once: exactly one succeeds (Task 3 test `test_concurrent_accepts_fill_last_spot_once`).
2. Deleting a team after these triggers exist still cascades its roster (existing `test_delete_team_cascades_roster`, run in Task 1).
3. A withdrawn re-invite of a former member keeps their row as history (Task 3 test `test_withdraw_reinvite_keeps_history`).
4. PID typed with spaces or capitals finds the player (Task 3 test `test_invite_pid_is_normalized`).
5. A captain handing off and then leaving works in two steps, and the old captain can't remove the new one (Task 4 test `test_handoff_then_leave`).

---

### Task 1: SQL files, triggers, migration

**Files:**
- Create: `db/roster.sql`
- Modify: `db/schema.sql` (delete the auth block after `IncidentReport`, lines 114-136)
- Rename: `backend/migrate_auth.py` → `backend/migrate.py`
- Modify: `compose.yaml` (mount `./db/auth.sql:/docker-entrypoint-initdb.d/02_auth.sql:ro`, `./db/roster.sql:/docker-entrypoint-initdb.d/03_roster.sql:ro`)
- Modify: `backend/main.py` `FRIENDLY_ERRORS`
- Modify: `README.md` setup steps (`python migrate.py`)
- Test: `backend/test_main.py`

**Interfaces:**
- Produces: `migrate.migrate()` applies `db/auth.sql` then `db/roster.sql`. Constraint names `team_captain_on_roster`, `roster_one_team_per_league`. Test module loads `schema.sql`, `auth.sql`, `roster.sql`, `seed.sql` in that order.

- [ ] **Step 1: Point the test setup at the split files and add trigger tests**

In `setUpModule` execute `db/schema.sql`, `db/auth.sql`, `db/roster.sql`, then `db/seed.sql`. Change `test_auth_migration_is_rerunnable` to `from migrate import migrate`. Add to a new `class TriggerTest(unittest.TestCase)`:

```python
def test_captain_cannot_lose_active_row(self):
    team_id, captain = sql("SELECT team_id, captain_id FROM Team ORDER BY team_id LIMIT 1")[0]
    with self.assertRaises(psycopg.errors.CheckViolation) as ctx:
        sql("UPDATE RosterMembership SET status = 'left' WHERE team_id = %s AND user_id = %s", (team_id, captain))
    self.assertEqual(ctx.exception.diag.constraint_name, "team_captain_on_roster")

def test_second_active_roster_in_league_rejected(self):
    # player: an active non-captain member of seeded team a; b: another team in a's league with no row for player
    player, a, b = sql("""
        SELECT r.user_id, r.team_id, t2.team_id FROM RosterMembership r
        JOIN Team t1 ON t1.team_id = r.team_id
        JOIN Team t2 ON t2.league_id = t1.league_id AND t2.team_id <> t1.team_id
        WHERE r.status = 'active' AND r.user_id <> t1.captain_id
          AND NOT EXISTS (SELECT 1 FROM RosterMembership x WHERE x.team_id = t2.team_id AND x.user_id = r.user_id)
        LIMIT 1""")[0]
    with self.assertRaises(psycopg.errors.CheckViolation) as ctx:
        sql("INSERT INTO RosterMembership (team_id, user_id, status, joined_at) VALUES (%s, %s, 'active', NOW())", (b, player))
    self.assertEqual(ctx.exception.diag.constraint_name, "roster_one_team_per_league")

```

`ApiTest.test_delete_team_cascades_roster` must keep passing; it is the cascade check (Review Focus 2).

- [ ] **Step 2: Run, expect failures**

Run: `cd backend && .venv/bin/python -m unittest test_main.TriggerTest -v`
Expected: setup error (`db/roster.sql` missing) or the two trigger tests FAIL.

- [ ] **Step 3: Write `db/roster.sql`**

Rerunnable: `CREATE OR REPLACE FUNCTION`, `DROP TRIGGER IF EXISTS`, `CREATE CONSTRAINT TRIGGER ... DEFERRABLE INITIALLY DEFERRED FOR EACH ROW`.
- `check_team_captain_on_roster()`: team id is `NEW.team_id` (Team or RosterMembership row) or `OLD.team_id` on DELETE. If the team no longer exists, return. If no `RosterMembership` row with that team, `user_id = captain_id`, `status = 'active'`, raise `team_captain_on_roster` with message `'Team % captain must be an active roster member'`. Triggers: `AFTER INSERT OR UPDATE OF captain_id ON Team`, `AFTER UPDATE OR DELETE ON RosterMembership`.
- `check_one_team_per_league()`: only when `NEW.status = 'active'`. `PERFORM 1 FROM Users WHERE user_id = NEW.user_id FOR UPDATE;` then if another active row for `NEW.user_id` on a different team in the same league exists, raise `roster_one_team_per_league`. Trigger: `AFTER INSERT OR UPDATE OF status ON RosterMembership`, not deferred (`NOT DEFERRABLE`), so the row lock serializes concurrent accepts.

Delete the auth block from `schema.sql`, rename and update the migration, mount the files in `compose.yaml`, add to `FRIENDLY_ERRORS`:
`"team_captain_on_roster": "A team's captain must be an active member of its roster."`,
`"roster_one_team_per_league": "A player can be on only one team per league."`

- [ ] **Step 4: Run all backend tests**

Run: `cd backend && .venv/bin/python -m unittest test_main`
Expected: all pass. Then `python migrate.py` against the dev DB prints success twice in a row.

- [ ] **Step 5: Commit** `git commit -m "Add roster triggers and split auth SQL out of schema"`

### Task 2: Registration rules

**Files:**
- Modify: `backend/main.py` (`register_team`, new helpers)
- Test: `backend/test_main.py`

**Interfaces:**
- Produces in `main.py`:
  - `LOCAL_TODAY = "(NOW() AT TIME ZONE 'America/New_York')::date"` (SQL fragment)
  - `fmt_date(d: date) -> str`
  - `ineligible_reason(conn, user_id: int, league_id: int) -> str | None` returning exactly one of `"Only active players can join teams."`, `f"Suspended until {fmt_date(d)}."`, `"Already on a team in this league."`, or `None`.
- Test fixture: `setUpModule` opens the test league (`league_id = MAX`) with `reg_open_at = NOW() - INTERVAL '1 day'`, `reg_close_at = NOW() + INTERVAL '30 days'`, `roster_lock_date = CURRENT_DATE + 30`. Tests that need other dates update and restore them in `try/finally`.

- [ ] **Step 1: Failing tests in `ApiTest`**

```python
def test_s2_registration_closed_is_409(self):
    # set reg_close_at = NOW() - 1 minute for self.league_id, restore after
    r = self.register()
    self.assertEqual((r.status_code, r.json()["detail"]), (409, "Registration for this league is not open."))

def test_s2_already_on_team_in_league_is_409(self):
    self.register()
    r = self.register(name=self.name + "b")  # same captain, same league
    self.assertEqual((r.status_code, r.json()["detail"]), (409, "Already on a team in this league."))
```

- [ ] **Step 2: Run, expect both FAIL (201)**

- [ ] **Step 3: Implement**

`register_team`: keep the existing 403 role/suspension check; then lock the user (`SELECT 1 FROM Users WHERE user_id = %s FOR UPDATE`), check the window (409 `"Registration for this league is not open."`; unknown league stays the FK 409), then `ineligible_reason`; return its message as 409.

- [ ] **Step 4: Run all backend tests, expect pass**
- [ ] **Step 5: Commit** `git commit -m "Enforce registration window and one team per league"`

### Task 3: Invitations

**Files:**
- Modify: `backend/main.py`
- Test: `backend/test_main.py`

**Interfaces:**
- Consumes: Task 2 helpers.
- Produces in `main.py`:
  - `team_rules(conn, team_id: int, *, for_update: bool = False) -> dict` with keys `team_id, team_name, captain_id, league_id, min_roster_size, max_roster_size, roster_lock_date, roster_locked, active_count`; 404 `"Team not found."`. `for_update` adds `FOR UPDATE OF t`.
  - `require_unlocked(team: dict) -> None`: 409 `f"The roster is locked (lock date {fmt_date(team['roster_lock_date'])})."`
  - `class Invite(BaseModel)`: `vt_pid` with the same `StringConstraints` as `auth.Login.vt_pid`, `extra="forbid"`.
  - Routes: `POST /api/teams/{team_id}/invites` (201), `GET /api/me/invites`, `POST /api/teams/{team_id}/invite/accept`, `POST /api/teams/{team_id}/invite/decline`, changed `DELETE /api/teams/{team_id}/invites/{player_id}`.
  - Invite response and `/api/me/invites` items: `{team_id, team_name, league_id, league_name, captain_first_name, captain_last_name, roster_lock_date, roster_locked, active_count, max_roster_size}` for `/api/me/invites`; `{user_id, first_name, last_name, status}` for the invite POST.

Order in every handler: load team (404) → authorization (403) → lock/state checks (409) → write.

- [ ] **Step 1: Failing tests** (new `class RosterTest(ApiTest)` reusing `register`/`sign_in`; a `third` player from `eligible_players(3)`)

```python
def invite_pid(self, team_id, user_id): ...  # POST with that user's vt_pid

def test_captain_invites_by_pid(self):       # 201, roster has (other, 'invited')
def test_invite_pid_is_normalized(self):     # "  SIMVT00XX " finds the player
def test_invite_unknown_pid_404(self):       # detail "No player with that PID."
def test_non_captain_cannot_invite_403(self):
def test_anonymous_invite_401(self):
def test_invite_twice_409(self):             # "That player is already invited to or on this team."
def test_invite_suspended_409(self):         # detail starts "Suspended until"
def test_invite_player_active_in_league_409(self):  # "Already on a team in this league."
def test_invite_after_lock_409(self):        # detail starts "The roster is locked"
def test_my_invites_lists_pending_only(self):
def test_accept_makes_active_and_declines_others(self):
    # other invited to team A and B in same league; accept A → A active, B 'declined'
def test_accept_without_invite_404(self):    # "You don't have a pending invite to this team."
def test_accept_full_team_409(self):         # set max_roster_size = 1 → "This team is full (1/1)."
def test_accept_after_lock_409(self):
def test_decline_after_lock_ok(self):        # 204, status 'declined'
def test_reinvite_reuses_row(self):          # 'left' row → invite → same membership_id, 'invited'
def test_withdraw_reinvite_keeps_history(self):  # row with joined_at set → withdraw → status 'removed'
def test_concurrent_accepts_fill_last_spot_once(self):
    # max_roster_size = 2, captain + two invitees; accept both via ThreadPoolExecutor with
    # separate TestClient instances → sorted status codes == [204, 409]
```

Accept/decline/withdraw return 204. Keep existing S4 withdraw tests passing.

- [ ] **Step 2: Run, expect FAIL (404/405 on new routes)**

- [ ] **Step 3: Implement**
  - Invite: captain only; `require_unlocked`; look up `Users WHERE LOWER(vt_pid) = %s` (404 `"No player with that PID."`); `ineligible_reason` → 409; existing row `invited`/`active` → 409; existing other status → `UPDATE ... SET status='invited', invited_at=NOW(), left_at=NULL`; else `INSERT`.
  - Withdraw: captain only, any time; `DELETE ... AND joined_at IS NULL`, else `UPDATE ... SET status='removed', left_at=NOW()` for an `invited` row with `joined_at` set; 404 unchanged when no invite.
  - Accept: `team_rules(for_update=True)`; caller's `invited` row (404); `require_unlocked`; `active_count >= max_roster_size` → 409 `f"This team is full ({active}/{max})."`; `ineligible_reason` → 409; set `active`, `joined_at=NOW()`; `UPDATE` caller's other `invited` rows in the same league to `declined`.
  - Decline: caller's `invited` row (404) → `declined`.

- [ ] **Step 4: Run all backend tests, expect pass**
- [ ] **Step 5: Commit** `git commit -m "Add roster invitations: invite by PID, accept, decline, withdraw history"`

### Task 4: Captain actions and team detail fields

**Files:**
- Modify: `backend/main.py` (`get_team`, new routes)
- Test: `backend/test_main.py`

**Interfaces:**
- Consumes: `team_rules`, `require_unlocked`.
- Produces: `DELETE /api/teams/{team_id}/members/{player_id}` (204), `POST /api/teams/{team_id}/leave` (204), `PUT /api/teams/{team_id}/captain` body `class NewCaptain(BaseModel): user_id: int` (`extra="forbid"`) → 200 `{team_id, captain_id}`. `GET /api/teams/{id}` adds `min_roster_size, max_roster_size, roster_lock_date, roster_locked`.

- [ ] **Step 1: Failing tests** (in `RosterTest`; make `other` active via invite + accept helper)

```python
def test_team_detail_has_roster_limits(self):  # keys present, roster_locked False
def test_captain_removes_member(self):          # 204, status 'removed', left_at set
def test_captain_cannot_remove_self_409(self):  # "The captain can't be removed. Hand off captaincy first."
def test_remove_non_member_404(self):           # "That player isn't an active member of this team."
def test_non_captain_cannot_remove_403(self):
def test_remove_after_lock_409(self):
def test_member_leaves(self):                   # 204, status 'left'
def test_captain_cannot_leave_409(self):        # "Hand off captaincy before leaving the team."
def test_leave_after_lock_409(self):
def test_handoff_to_active_member(self):        # 200, captain_id == other
def test_handoff_to_non_member_409(self):       # "The new captain must be an active member of this team."
def test_non_captain_cannot_handoff_403(self):
def test_handoff_after_lock_ok(self):           # allowed after lock date
def test_handoff_then_leave(self):              # old captain leaves (204); old captain can't remove new one (403)
```

- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: Implement** the three routes and the four `get_team` fields (join League; `roster_locked` computed with `LOCAL_TODAY`). Leave: 404 `"You aren't an active member of this team."` when the caller has no active row.
- [ ] **Step 4: Run all backend tests, expect pass**
- [ ] **Step 5: Commit** `git commit -m "Add captain actions: remove member, leave team, hand off captaincy"`

### Task 5: Frontend

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/components/Teams.tsx`, `frontend/src/components/TeamDetail.tsx`, `frontend/src/styles/TeamDetail.css` only if a new class is needed (reuse `panel`, `notice`, `button-*`, `pill-*`, `form-row`, `field`).

**Interfaces:**
- Consumes: Task 3/4 routes and shapes.
- Produces: `Team` gains `min_roster_size: number; max_roster_size: number; roster_lock_date: string; roster_locked: boolean`. New `export type Invite` matching `/api/me/invites` items. Pills for `declined`, `removed`, `left` reuse `pill-${status}`.

- [ ] **Step 1: Teams page** "Your invitations" panel above the directory when `user` is set and the list is non-empty; `useApi<Invite[]>(user ? '/api/me/invites' : null)`; Accept/Decline call the routes, then reload invites and teams; errors shown in a `notice-error`.
- [ ] **Step 2: Team detail** per spec: meta "Roster N / max", "Roster locks <date>" or "Roster locked"; captain invite-by-PID form, hand-off `<select>` of active non-captain members with `window.confirm`; Remove on active non-captain rows (confirm); Leave for active non-captain viewer (confirm); Accept/Decline banner for a viewer whose row is `invited`; roster-changing buttons disabled with a note when `roster_locked` (hand-off, withdraw, decline stay enabled).
- [ ] **Step 3: Verify**
Run: `cd frontend && npx tsc -b && npm run lint`
Expected: no errors.
- [ ] **Step 4: Manual run** in the browser pane: open a Spring league locally (README snippet from Task 6), captain `simvt0001` registers a team and invites `simvt0002`; `simvt0002` accepts from the Teams panel; captain hands off; old captain leaves. Screens show the new states.
- [ ] **Step 5: Commit** `git commit -m "Add roster invitations and captain actions to the UI"`

### Task 6: Docs and final verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1:** Rewrite the API table: remove the "no login" paragraph, the `/api/users` row and every `user_id` body/query field; add `/api/auth/*` routes and every route from Tasks 3–4 with caller and status codes. Add a "Local demo dates" note with the SQL to open a Spring league:
`UPDATE League SET reg_open_at = NOW() - INTERVAL '1 day' WHERE term = 'Spring 2027';`
- [ ] **Step 2:** Run `cd backend && .venv/bin/python -m unittest test_main` and `cd frontend && npx tsc -b && npm run lint`. Expected: all pass, no errors.
- [ ] **Step 3: Commit** `git commit -m "Document roster API and local demo dates"`
