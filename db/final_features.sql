-- Rerunnable upgrade. Applied after phase3.sql and before demo seed data.
ALTER TABLE Game DROP CONSTRAINT IF EXISTS game_facility_id_start_time_key;
CREATE UNIQUE INDEX IF NOT EXISTS game_live_facility_start ON Game (facility_id, start_time) WHERE status <> 'cancelled';

CREATE TABLE IF NOT EXISTS MembershipPeriod (
    period_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    membership_id INT REFERENCES RosterMembership(membership_id) ON DELETE SET NULL,
    team_id INT REFERENCES Team(team_id) ON DELETE SET NULL,
    user_id INT NOT NULL REFERENCES Users(user_id) ON DELETE CASCADE,
    team_name VARCHAR(60) NOT NULL,
    league_name TEXT NOT NULL,
    joined_at TIMESTAMPTZ NOT NULL,
    left_at TIMESTAMPTZ,
    end_reason VARCHAR(20)
);
CREATE UNIQUE INDEX IF NOT EXISTS membership_period_start ON MembershipPeriod (membership_id, joined_at);
CREATE UNIQUE INDEX IF NOT EXISTS membership_period_open ON MembershipPeriod (membership_id) WHERE end_reason IS NULL AND membership_id IS NOT NULL;

-- Only the latest period can be recovered from existing rows; older overwritten periods are unavailable.
INSERT INTO MembershipPeriod (membership_id, team_id, user_id, team_name, league_name, joined_at, left_at, end_reason)
SELECT r.membership_id, r.team_id, r.user_id, t.team_name, l.league_name, r.joined_at,
       CASE WHEN r.status = 'active' THEN NULL ELSE r.left_at END,
       CASE WHEN r.status <> 'active' THEN CASE WHEN r.status = 'left' THEN 'left' ELSE 'removed' END END
FROM RosterMembership r JOIN Team t ON t.team_id = r.team_id JOIN LeagueView l ON l.league_id = t.league_id
WHERE r.joined_at IS NOT NULL
ON CONFLICT (membership_id, joined_at) DO NOTHING;

CREATE OR REPLACE FUNCTION record_membership_period() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        UPDATE MembershipPeriod SET left_at = COALESCE(OLD.left_at, NOW()), end_reason = 'team_deleted'
        WHERE membership_id = OLD.membership_id AND end_reason IS NULL;
        RETURN OLD;
    END IF;
    IF NEW.joined_at IS NOT NULL AND (TG_OP = 'INSERT' OR (NEW.status = 'active' AND OLD.status <> 'active')) THEN
        INSERT INTO MembershipPeriod (membership_id, team_id, user_id, team_name, league_name, joined_at, left_at, end_reason)
        SELECT NEW.membership_id, NEW.team_id, NEW.user_id, t.team_name, l.league_name, NEW.joined_at,
               CASE WHEN NEW.status = 'active' THEN NULL ELSE NEW.left_at END,
               CASE WHEN NEW.status <> 'active' THEN CASE WHEN NEW.status = 'left' THEN 'left' ELSE 'removed' END END
        FROM Team t JOIN LeagueView l ON l.league_id = t.league_id WHERE t.team_id = NEW.team_id
        ON CONFLICT (membership_id, joined_at) DO NOTHING;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.status = 'active' AND NEW.status IN ('left', 'removed') THEN
        UPDATE MembershipPeriod SET left_at = COALESCE(NEW.left_at, NOW()), end_reason = NEW.status
        WHERE membership_id = NEW.membership_id AND end_reason IS NULL;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS roster_membership_period ON RosterMembership;
DROP TRIGGER IF EXISTS roster_membership_period_delete ON RosterMembership;
CREATE TRIGGER roster_membership_period AFTER INSERT OR UPDATE ON RosterMembership
FOR EACH ROW EXECUTE FUNCTION record_membership_period();
CREATE TRIGGER roster_membership_period_delete BEFORE DELETE ON RosterMembership
FOR EACH ROW EXECUTE FUNCTION record_membership_period();
