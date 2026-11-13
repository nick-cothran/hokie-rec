# Hokie Rec ER diagram (Phase III)

Built from `db/schema.sql`, `db/auth.sql`, `db/phase3.sql` and `db/final_features.sql`.

```mermaid
erDiagram
    Sport ||--o{ League : "sets roster limits for"
    League ||--o{ Team : "has"
    League ||--o{ Game : "schedules"
    Users ||--o{ Team : "captains"
    Team ||--o{ RosterMembership : "has"
    Users ||--o{ RosterMembership : "joins"
    Users ||--o{ MembershipPeriod : "has history"
    RosterMembership |o--o{ MembershipPeriod : "records periods"
    Team |o--o{ MembershipPeriod : "appears in history"
    Facility ||--o{ Game : "hosts"
    Team |o--o{ Game : "plays home"
    Team |o--o{ Game : "plays away"
    Game |o--o{ Game : "winner advances to"
    Game ||--o{ ScoreReport : "has"
    Users ||--o{ ScoreReport : "submits"
    Team |o--o{ ScoreReport : "forfeits"
    Game ||--o{ OfficiatingAssignment : "needs"
    Users ||--o{ OfficiatingAssignment : "officiates"
    Users ||--o{ OfficiatingAssignment : "assigns"
    Game ||--o{ IncidentReport : "has"
    Users ||--o{ IncidentReport : "files"
    Users |o--o{ IncidentReport : "is involved in"
    Users |o--o{ IncidentReport : "reviews"
    Users ||--o| UserCredentials : "has"
    Users ||--o{ AuthSession : "has"

    Sport {
        int sport_id PK
        varchar sport_name UK
        int min_roster_size "0 or more, at most max"
        int max_roster_size
    }

    League {
        int league_id PK
        int sport_id FK "UK with category, skill_level, term"
        varchar category
        varchar skill_level
        varchar term
        date start_date "on or before end_date"
        date end_date
        timestamptz reg_open_at "before reg_close_at"
        timestamptz reg_close_at
        date roster_lock_date
    }

    Users {
        int user_id PK
        varchar vt_pid UK "unique ignoring case"
        varchar first_name
        varchar last_name
        varchar email UK "unique ignoring case"
        varchar phone "optional"
        varchar role "player, official or admin"
        date suspended_until "optional"
        boolean is_active
        timestamptz created_at
    }

    Team {
        int team_id PK
        int league_id FK
        int captain_id FK "Users; an active member"
        varchar team_name "UK within the league"
        varchar status "active or inactive"
        timestamptz registered_at
    }

    RosterMembership {
        int membership_id PK
        int team_id FK "UK with user_id"
        int user_id FK
        varchar status "invited, active, declined, removed or left"
        timestamptz invited_at
        timestamptz joined_at "optional"
        timestamptz left_at "optional"
    }

    MembershipPeriod {
        int period_id PK
        int membership_id FK "optional after membership deletion"
        int team_id FK "optional after team deletion"
        int user_id FK
        varchar team_name "snapshot"
        text league_name "snapshot"
        timestamptz joined_at
        timestamptz left_at "optional"
        varchar end_reason "left, removed or team_deleted"
    }

    Facility {
        int facility_id PK
        varchar facility_name UK
        varchar location
    }

    Game {
        int game_id PK
        int league_id FK
        int facility_id FK "unique with start_time for non-cancelled games"
        int home_team_id FK "Team; empty until a playoff slot is decided"
        int away_team_id FK "Team; differs from home"
        int next_game_id FK "Game the winner plays next"
        timestamptz start_time
        timestamptz end_time "after start_time"
        int playoff_round "empty for regular season"
        varchar status "scheduled, completed or cancelled"
    }

    ScoreReport {
        int report_id PK
        int game_id FK
        int submitted_by FK "Users; the game's assigned official"
        int forfeit_team_id FK "Team; one of the game's teams"
        int home_score "0 or more; set with away_score"
        int away_score "0 or more"
        timestamptz submitted_at
    }

    OfficiatingAssignment {
        int assignment_id PK
        int game_id FK "UK with official_id"
        int official_id FK "Users; an official"
        int assigned_by FK "Users; an admin"
        varchar position
        varchar status "assigned, accepted, declined or completed"
        timestamptz assigned_at
    }

    IncidentReport {
        int incident_id PK
        int game_id FK
        int filed_by FK "Users; an official"
        int involved_user_id FK "Users; optional"
        int reviewed_by FK "Users; an admin, optional"
        varchar incident_type
        text description
        varchar status "open, reviewed or dismissed"
        timestamptz filed_at
    }

    UserCredentials {
        int user_id PK, FK
        text password_hash
    }

    AuthSession {
        char token_hash PK
        int user_id FK
        timestamptz expires_at
    }

    AuthLoginAttempt {
        char identifier_hash PK "not linked to Users"
        int attempts
        timestamptz window_start
    }
```

## Rules the diagram can't show

- **Views.** `LeagueView` is a league with its sport's name and roster limits, plus a display name built from the league's columns (e.g. "Coed Soccer, Recreational, Fall 2026"). `LatestScoreReport` is each game's newest score report, the one that counts.
- **Score reports** are never edited; a correction is a new report. Each report holds a result: a forfeit, or both scores.
- **Playoff games:** a game is a playoff game when `playoff_round` is set. Its winner fills a team slot of `next_game_id`. Individual playoff games cannot be rescheduled because feeder order uses start times.
- **Facility slots:** non-cancelled games must have a unique facility and start time; cancelled games leave the slot available.
- **Membership history:** each join creates a period; leave, removal, or team deletion closes it. Migration can recover only the last period still present in each old roster row.
- **Rosters:** a player is active on at most one team per league, and a team's captain is always an active member of it.
- **Game teams** play in the game's league.
- **Deleting:** deleting a team removes its roster rows but retains membership periods with team and league name snapshots. Deleting a game removes its score reports and assignments, but is blocked while it has incident reports. Deleting a user removes their credentials, sessions, and membership history.
