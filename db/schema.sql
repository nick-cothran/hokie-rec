CREATE TABLE League (
    league_id           INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    league_name         VARCHAR(100) NOT NULL,
    sport_name          VARCHAR(50) NOT NULL,
    category            VARCHAR(10) NOT NULL,
    skill_level         VARCHAR(20) NOT NULL,
    term                VARCHAR(20) NOT NULL,
    start_date          DATE NOT NULL,
    end_date            DATE NOT NULL,
    reg_open_at         TIMESTAMPTZ NOT NULL,
    reg_close_at        TIMESTAMPTZ NOT NULL,
    roster_lock_date    DATE NOT NULL,
    min_roster_size     INT NOT NULL,
    max_roster_size     INT NOT NULL,
    CHECK (reg_open_at < reg_close_at),
    CHECK (min_roster_size <= max_roster_size),
    CHECK (start_date <= end_date),
    CHECK (min_roster_size >= 0)
);

CREATE TABLE Users (
    user_id             INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vt_pid              VARCHAR(40) UNIQUE NOT NULL,
    first_name          VARCHAR(50) NOT NULL,
    last_name           VARCHAR(50) NOT NULL,
    email               VARCHAR(100) NOT NULL UNIQUE,
    phone               VARCHAR(20) NOT NULL,
    role                VARCHAR(10) NOT NULL,
    suspended_until     DATE NULL,
    is_active           BOOLEAN NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL,
    CHECK (role IN ('player', 'official', 'admin'))

);

CREATE TABLE Team (
    team_id             INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    league_id           INT NOT NULL REFERENCES League(league_id) ON DELETE RESTRICT,
    captain_id          INT NOT NULL REFERENCES Users(user_id) ON DELETE RESTRICT,
    team_name           VARCHAR(60) NOT NULL,
    status              VARCHAR(15) NOT NULL,
    registered_at       TIMESTAMPTZ NOT NULL,
    UNIQUE (league_id, team_name)
);

CREATE TABLE RosterMembership (
    membership_id       INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    team_id             INT NOT NULL REFERENCES Team(team_id) ON DELETE CASCADE,
    user_id             INT NOT NULL REFERENCES Users(user_id) ON DELETE RESTRICT,
    status              VARCHAR(15) NOT NULL,
    invited_at          TIMESTAMPTZ NOT NULL,
    joined_at           TIMESTAMPTZ,
    left_at             TIMESTAMPTZ,
    UNIQUE (team_id, user_id)
);

CREATE TABLE Facility (
    facility_id         INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    facility_name       VARCHAR(60) NOT NULL UNIQUE,
    location            VARCHAR(100) NOT NULL
);

CREATE TABLE Game (
    game_id             INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    league_id           INT NOT NULL REFERENCES League(league_id) ON DELETE RESTRICT,
    facility_id         INT NOT NULL REFERENCES Facility(facility_id) ON DELETE RESTRICT,
    home_team_id        INT REFERENCES Team(team_id) ON DELETE RESTRICT,
    away_team_id        INT REFERENCES Team(team_id) ON DELETE RESTRICT,
    next_game_id        INT REFERENCES Game(game_id) ON DELETE SET NULL,
    start_time          TIMESTAMPTZ NOT NULL,
    end_time            TIMESTAMPTZ NOT NULL,
    game_type           VARCHAR(10) NOT NULL,
    playoff_round       INT NULL,
    status              VARCHAR(10) NOT NULL,
    UNIQUE (facility_id, start_time),
    CHECK(home_team_id <> away_team_id),
    CHECK(end_time > start_time)
);

CREATE TABLE ScoreReport (
    report_id           INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id             INT NOT NULL REFERENCES Game(game_id) ON DELETE CASCADE,
    submitted_by        INT NOT NULL REFERENCES Users(user_id) ON DELETE RESTRICT,
    forfeit_team_id     INT REFERENCES Team(team_id) ON DELETE RESTRICT,
    home_score          INT,
    away_score          INT,
    is_forfeit          BOOLEAN NOT NULL,
    submitted_at        TIMESTAMPTZ NOT NULL,
    CHECK (home_score >= 0 AND away_score >= 0)
);

CREATE TABLE OfficiatingAssignment (
    assignment_id       INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id             INT NOT NULL REFERENCES Game(game_id) ON DELETE CASCADE,
    official_id         INT NOT NULL REFERENCES Users(user_id) ON DELETE RESTRICT,
    assigned_by         INT NOT NULL REFERENCES Users(user_id) ON DELETE RESTRICT,
    position            VARCHAR(20) NOT NULL,
    status              VARCHAR(15) NOT NULL,
    assigned_at         TIMESTAMPTZ NOT NULL,
    UNIQUE(game_id, official_id)
);

CREATE TABLE IncidentReport (
    incident_id         INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id             INT NOT NULL REFERENCES Game(game_id) ON DELETE RESTRICT,
    filed_by            INT NOT NULL REFERENCES Users(user_id) ON DELETE RESTRICT,
    involved_user_id    INT REFERENCES Users(user_id) ON DELETE RESTRICT,
    reviewed_by         INT REFERENCES Users(user_id) ON DELETE RESTRICT,
    incident_type       VARCHAR(20) NOT NULL,
    description         TEXT NOT NULL,
    status              VARCHAR(15) NOT NULL,
    filed_at            TIMESTAMPTZ NOT NULL
);