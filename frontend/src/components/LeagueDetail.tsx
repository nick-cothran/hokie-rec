import '../styles/LeagueDetail.css'
import { Link, useParams } from 'react-router-dom'
import { query, useApi, type League, type TeamSummary } from '../api'
import TeamTable from './TeamTable'

function LeagueDetail() {
  const { leagueId } = useParams()
  const id = Number(leagueId)
  const valid = Number.isInteger(id) && id > 0

  const leagues = useApi<League[]>(valid ? '/api/leagues' : null)
  const teams = useApi<TeamSummary[]>(valid ? `/api/teams${query({ league_id: id })}` : null)
  const league = leagues.data?.find(l => l.league_id === id)

  if (!valid || (leagues.data && !league)) {
    return (
      <main className="content-page detail-page league-detail-page">
        <Link className="back-link" to="/leagues">← All leagues</Link>
        <section className="empty-state">
          <p className="eyebrow">League details</p>
          <h1>League not found</h1>
          <p>There's no league with id “{leagueId}”.</p>
          <Link className="button button-primary" to="/leagues">Back to leagues</Link>
        </section>
      </main>
    )
  }

  return (
    <main className="content-page detail-page league-detail-page">
      <Link className="back-link" to="/leagues">← All leagues</Link>
      {leagues.error && <p className="notice notice-error" role="alert">{leagues.error}</p>}
      {!league && !leagues.error && <p className="loading">Loading league…</p>}
      {league && (
        <div className="stack">
          <div className="page-intro">
            <p className="eyebrow">{league.term}</p>
            <div className="intro-row">
              <div>
                <h1>{league.league_name}</h1>
                <ul className="meta-list">
                  <li>Sport <strong>{league.sport_name}</strong></li>
                  <li>Category <strong>{league.category}</strong></li>
                  <li>Level <strong>{league.skill_level}</strong></li>
                </ul>
              </div>
              <Link className="button button-primary" to={`/teams/new${query({ league: id })}`}>Register a team</Link>
            </div>
          </div>
          <section>
            <div className="section-heading"><h2>Teams</h2></div>
            {teams.error && <p className="notice notice-error" role="alert">{teams.error}</p>}
            {teams.loading && !teams.data && <p className="loading">Loading teams…</p>}
            {teams.data && teams.data.length === 0 && (
              <div className="empty-state"><h2>No teams yet</h2><p>Be the first to register a team in this league.</p></div>
            )}
            {teams.data && teams.data.length > 0 && <TeamTable teams={teams.data} showLeague={false} />}
          </section>
        </div>
      )}
    </main>
  )
}

export default LeagueDetail
