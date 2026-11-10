-- Roster invariants (Phase II/III). Additive and rerunnable; existing data is preserved.
-- Errors use SQLSTATE 23514 with a constraint name so the API can show a readable message.

-- Every team's captain has an active roster row on that team. Deferred to commit because
-- registering a team inserts the team and the captain's roster row in one transaction.
CREATE OR REPLACE FUNCTION check_team_captain_on_roster() RETURNS trigger AS $$
DECLARE
    tid INT := CASE WHEN TG_OP = 'DELETE' THEN OLD.team_id ELSE NEW.team_id END;
BEGIN
    -- A deleted team (roster rows cascade) no longer exists and is skipped.
    IF EXISTS (
        SELECT 1 FROM Team t
        WHERE t.team_id = tid AND NOT EXISTS (
            SELECT 1 FROM RosterMembership r
            WHERE r.team_id = t.team_id AND r.user_id = t.captain_id AND r.status = 'active')
    ) THEN
        RAISE EXCEPTION 'Team % captain must be an active roster member', tid
            USING ERRCODE = 'check_violation', CONSTRAINT = 'team_captain_on_roster';
    END IF;
    RETURN NULL;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS team_captain_on_roster ON Team;
CREATE CONSTRAINT TRIGGER team_captain_on_roster
    AFTER INSERT OR UPDATE OF captain_id ON Team
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_team_captain_on_roster();

DROP TRIGGER IF EXISTS roster_captain_on_roster ON RosterMembership;
CREATE CONSTRAINT TRIGGER roster_captain_on_roster
    AFTER UPDATE OR DELETE ON RosterMembership
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_team_captain_on_roster();

-- A player is active on at most one team per league. Locking the player's Users row
-- makes concurrent activations for the same player run one after another.
CREATE OR REPLACE FUNCTION check_one_team_per_league() RETURNS trigger AS $$
BEGIN
    IF NEW.status = 'active' THEN
        PERFORM 1 FROM Users WHERE user_id = NEW.user_id FOR UPDATE;
        IF EXISTS (
            SELECT 1 FROM RosterMembership r
            JOIN Team t ON t.team_id = r.team_id
            JOIN Team mine ON mine.team_id = NEW.team_id
            WHERE r.user_id = NEW.user_id AND r.status = 'active'
              AND r.team_id <> NEW.team_id AND t.league_id = mine.league_id
        ) THEN
            RAISE EXCEPTION 'Player % is already active on a team in this league', NEW.user_id
                USING ERRCODE = 'check_violation', CONSTRAINT = 'roster_one_team_per_league';
        END IF;
    END IF;
    RETURN NULL;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS roster_one_team_per_league ON RosterMembership;
CREATE TRIGGER roster_one_team_per_league
    AFTER INSERT OR UPDATE OF status ON RosterMembership
    FOR EACH ROW EXECUTE FUNCTION check_one_team_per_league();
