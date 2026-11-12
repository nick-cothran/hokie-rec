-- Phase III rules: the normalized schema's views and the cross-table rules a plain
-- constraint can't express. Rerunnable. On a database created before Phase III, it first
-- converts the old tables; it stops without changing anything if a dropped column holds
-- data that the new design can't rebuild.
-- Errors use SQLSTATE 23514 with a constraint name so the API can show a readable message.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = current_schema() AND table_name = 'league' AND column_name = 'sport_name') THEN
        IF EXISTS (SELECT 1 FROM League GROUP BY sport_name
                   HAVING COUNT(DISTINCT (min_roster_size, max_roster_size)) > 1) THEN
            RAISE EXCEPTION 'Leagues of the same sport have different roster limits; make them match first';
        END IF;
        IF EXISTS (SELECT 1 FROM Game WHERE game_type NOT IN ('regular', 'playoff')
                      OR (game_type = 'playoff') <> (playoff_round IS NOT NULL)) THEN
            RAISE EXCEPTION 'Game.game_type disagrees with playoff_round; fix those games first';
        END IF;
        IF EXISTS (SELECT 1 FROM ScoreReport WHERE is_forfeit <> (forfeit_team_id IS NOT NULL)) THEN
            RAISE EXCEPTION 'ScoreReport.is_forfeit disagrees with forfeit_team_id; fix those reports first';
        END IF;

        CREATE TABLE Sport (
            sport_id            INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            sport_name          VARCHAR(50) NOT NULL UNIQUE,
            min_roster_size     INT NOT NULL,
            max_roster_size     INT NOT NULL,
            CHECK (min_roster_size <= max_roster_size),
            CHECK (min_roster_size >= 0)
        );
        INSERT INTO Sport (sport_name, min_roster_size, max_roster_size)
            SELECT DISTINCT sport_name, min_roster_size, max_roster_size FROM League ORDER BY sport_name;
        ALTER TABLE League ADD COLUMN sport_id INT REFERENCES Sport(sport_id) ON DELETE RESTRICT;
        UPDATE League l SET sport_id = s.sport_id FROM Sport s WHERE s.sport_name = l.sport_name;
        ALTER TABLE League ALTER COLUMN sport_id SET NOT NULL,
            DROP COLUMN league_name, DROP COLUMN sport_name, DROP COLUMN min_roster_size, DROP COLUMN max_roster_size,
            ADD UNIQUE (sport_id, category, skill_level, term);
        ALTER TABLE Game DROP COLUMN game_type;
        ALTER TABLE ScoreReport DROP COLUMN is_forfeit;
        ALTER TABLE Users ALTER COLUMN phone DROP NOT NULL;
    END IF;
END $$;

-- Views are dropped and recreated so a rerun picks up columns added to League or ScoreReport later.
-- League with its sport's details and display name, e.g. "Coed Soccer, Recreational, Fall 2026"
DROP VIEW IF EXISTS LeagueView;
CREATE VIEW LeagueView AS
SELECT l.*, s.sport_name, s.min_roster_size, s.max_roster_size,
       l.category || ' ' || s.sport_name || ', ' || l.skill_level || ', ' || l.term AS league_name
FROM League l JOIN Sport s ON s.sport_id = l.sport_id;

-- The report that counts for each game: corrections are new reports, so the newest wins
DROP VIEW IF EXISTS LatestScoreReport;
CREATE VIEW LatestScoreReport AS
SELECT DISTINCT ON (game_id) * FROM ScoreReport ORDER BY game_id, submitted_at DESC, report_id DESC;

-- A game's teams play in the game's league. Either may be empty for a future playoff game.
CREATE OR REPLACE FUNCTION check_game_teams_in_league() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM Team WHERE team_id IN (NEW.home_team_id, NEW.away_team_id)
                                    AND league_id <> NEW.league_id) THEN
        RAISE EXCEPTION 'Game teams must play in the game''s league'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'game_teams_in_league';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS game_teams_in_league ON Game;
CREATE TRIGGER game_teams_in_league
    BEFORE INSERT OR UPDATE OF league_id, home_team_id, away_team_id ON Game
    FOR EACH ROW EXECUTE FUNCTION check_game_teams_in_league();

-- Raises unless user_id (when set) has the role; shared by the role triggers below
CREATE OR REPLACE FUNCTION require_role(user_id INT, role TEXT, rule TEXT) RETURNS void AS $$
BEGIN
    IF user_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM Users u WHERE u.user_id = require_role.user_id
                                                                   AND u.role = require_role.role) THEN
        RAISE EXCEPTION 'User % must be an %', user_id, role
            USING ERRCODE = 'check_violation', CONSTRAINT = rule;
    END IF;
END $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION check_assignment_roles() RETURNS trigger AS $$
BEGIN
    PERFORM require_role(NEW.official_id, 'official', 'assignment_official_role');
    PERFORM require_role(NEW.assigned_by, 'admin', 'assignment_by_admin');
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS assignment_roles ON OfficiatingAssignment;
CREATE TRIGGER assignment_roles
    BEFORE INSERT OR UPDATE OF official_id, assigned_by ON OfficiatingAssignment
    FOR EACH ROW EXECUTE FUNCTION check_assignment_roles();

CREATE OR REPLACE FUNCTION check_incident_roles() RETURNS trigger AS $$
BEGIN
    PERFORM require_role(NEW.filed_by, 'official', 'incident_filed_by_official');
    PERFORM require_role(NEW.reviewed_by, 'admin', 'incident_reviewed_by_admin');
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS incident_roles ON IncidentReport;
CREATE TRIGGER incident_roles
    BEFORE INSERT OR UPDATE OF filed_by, reviewed_by ON IncidentReport
    FOR EACH ROW EXECUTE FUNCTION check_incident_roles();

-- Only the game's assigned official submits a score report (one who declined the shift doesn't
-- count), a forfeit names one of the game's two teams, and reports are never edited.
CREATE OR REPLACE FUNCTION check_score_report() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'Score reports can''t be edited; submit a new report instead'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'scorereport_no_edits';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM OfficiatingAssignment
                   WHERE game_id = NEW.game_id AND official_id = NEW.submitted_by AND status <> 'declined') THEN
        RAISE EXCEPTION 'Only the official assigned to game % can submit its score', NEW.game_id
            USING ERRCODE = 'check_violation', CONSTRAINT = 'scorereport_by_assigned_official';
    END IF;
    IF NEW.forfeit_team_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM Game WHERE game_id = NEW.game_id AND NEW.forfeit_team_id IN (home_team_id, away_team_id)) THEN
        RAISE EXCEPTION 'The forfeiting team must play in game %', NEW.game_id
            USING ERRCODE = 'check_violation', CONSTRAINT = 'scorereport_forfeit_team_in_game';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS score_report_rules ON ScoreReport;
CREATE TRIGGER score_report_rules
    BEFORE INSERT OR UPDATE ON ScoreReport
    FOR EACH ROW EXECUTE FUNCTION check_score_report();

-- Allowed status values, and a score report must hold a result: a forfeit, or both scores
-- (seeded forfeits also record a scoreline, so scores alongside a forfeit stay allowed).
-- Dropped and re-added so a rerun applies any change to the lists.
ALTER TABLE Team DROP CONSTRAINT IF EXISTS team_status_valid,
    ADD CONSTRAINT team_status_valid CHECK (status IN ('active', 'inactive'));
ALTER TABLE RosterMembership DROP CONSTRAINT IF EXISTS rostermembership_status_valid,
    ADD CONSTRAINT rostermembership_status_valid CHECK (status IN ('invited', 'active', 'declined', 'removed', 'left'));
ALTER TABLE Game DROP CONSTRAINT IF EXISTS game_status_valid,
    ADD CONSTRAINT game_status_valid CHECK (status IN ('scheduled', 'completed', 'cancelled'));
ALTER TABLE OfficiatingAssignment DROP CONSTRAINT IF EXISTS officiatingassignment_status_valid,
    ADD CONSTRAINT officiatingassignment_status_valid CHECK (status IN ('assigned', 'accepted', 'declined', 'completed'));
ALTER TABLE IncidentReport DROP CONSTRAINT IF EXISTS incidentreport_status_valid,
    ADD CONSTRAINT incidentreport_status_valid CHECK (status IN ('open', 'reviewed', 'dismissed'));
ALTER TABLE ScoreReport DROP CONSTRAINT IF EXISTS scorereport_has_result,
    ADD CONSTRAINT scorereport_has_result CHECK ((home_score IS NULL) = (away_score IS NULL)
                                                 AND (forfeit_team_id IS NOT NULL OR home_score IS NOT NULL));
