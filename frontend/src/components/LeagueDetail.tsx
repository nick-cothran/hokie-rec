import '../styles/LeagueDetail.css'
import { Link, useParams } from 'react-router-dom'
import { formatCampusDate, query, useApi, type League, type TeamSummary } from '../api'
import TeamTable from './TeamTable'
import Playoffs from './Playoffs'
import { useAuth } from '../auth'

function LeagueDetail() {
  const { user, loading: checkingSession } = useAuth()
  const canRegister = !checkingSession && (!user || user.role === 'player')
  const { leagueId } = useParams()
  const id = Number(leagueId)
  const valid = Number.isInteger(id) && id > 0

  const leagues = useApi<League[]>(valid ? '/api/leagues' : null)
  const teams = useApi<TeamSummary[]>(valid ? `/api/teams${query({ league_id: id })}` : null)
  const league = leagues.data?.find(l => l.league_id === id)
  const registrationOpen = !!league?.registration_open

  if (!valid || (leagues.data && !league)) {
    return (
      <main className="content-page detail-page league-detail-page">
        <nav className="detail-breadcrumb" aria-label="League navigation"><Link className="detail-back" to="/leagues"><span aria-hidden="true">←</span> All leagues</Link></nav>
        <section className="empty-state">
          <h1>League not found</h1>
          <p>There's no league with id “{leagueId}”.</p>
          <Link className="button button-primary" to="/leagues">Back to leagues</Link>
        </section>
      </main>
    )
  }

  return (
    <main className="content-page detail-page league-detail-page">
      {!league && <nav className="detail-breadcrumb" aria-label="League navigation"><Link className="detail-back" to="/leagues"><span aria-hidden="true">←</span> All leagues</Link></nav>}
      {leagues.error && <p className="notice notice-error" role="alert">{leagues.error}</p>}
      {!league && !leagues.error && <p className="loading">Loading league…</p>}
      {league && (
        <div className="stack">
          <div className="page-intro">
            <div className="detail-top-actions">
              <Link className="detail-back" to="/leagues"><span aria-hidden="true">←</span> All leagues</Link>
              <nav className="detail-actions" aria-label="League links"><Link to={`/schedule?league=${id}`}>Schedule <span aria-hidden="true">→</span></Link><Link to={`/reports?league=${id}`}>Standings <span aria-hidden="true">→</span></Link></nav>
            </div>
            <p className="eyebrow">{league.term}</p>
            <div className="intro-row">
              <div>
                <h1>{league.league_name}</h1>
                <ul className="meta-list">
                  <li>Sport: <strong>{league.sport_name}</strong></li>
                  <li>Category: <strong>{league.category}</strong></li>
                  <li>Level: <strong>{league.skill_level}</strong></li>
                  <li>Registration: <strong>{league.registration_status === 'upcoming' ? `Opens ${formatCampusDate(league.reg_open_at)}` : league.registration_status === 'open' ? 'Open' : 'Closed'}</strong></li>
                </ul>
              </div>
              {canRegister && registrationOpen && <Link className="button button-primary" to={`/teams/new${query({ league: id })}`}>Register a team</Link>}
            </div>
          </div>
          <section>
            <div className="section-heading"><h2>Teams</h2></div>
            {teams.error && <p className="notice notice-error" role="alert">{teams.error}</p>}
            {teams.loading && !teams.data && <p className="loading">Loading teams…</p>}
            {teams.data && teams.data.length === 0 && (
              <div className="empty-state"><h2>No teams yet</h2><p>{canRegister && registrationOpen ? 'Be the first to register a team in this league.' : 'No teams have registered for this league.'}</p></div>
            )}
            {teams.data && teams.data.length > 0 && <TeamTable teams={teams.data} showLeague={false} />}
          </section>
          <Playoffs leagueId={id} />
        </div>
      )}
    </main>
  )
}

export default LeagueDetail
