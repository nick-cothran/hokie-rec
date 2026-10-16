import '../styles/Teams.css'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { query, useApi, type League, type TeamSummary } from '../api'
import TeamTable from './TeamTable'

function Teams() {
  const [params, setParams] = useSearchParams()
  const notice: string | undefined = useLocation().state?.notice
  const leagueId = params.get('league_id') ?? ''

  const leagues = useApi<League[]>('/api/leagues')
  const teams = useApi<TeamSummary[]>(`/api/teams${query({ league_id: leagueId })}`)

  return (
    <main className="content-page teams-page">
      <div className="page-intro">
        <p className="eyebrow">Team directory</p>
        <div className="intro-row">
          <div><h1>Meet the teams.</h1><p>Open a team to see its roster. Captains can rename their team and manage invites.</p></div>
          <Link className="button button-primary" to={`/teams/new${query({ league: leagueId })}`}>Register a team</Link>
        </div>
      </div>

      <form className="filters" role="search" onSubmit={e => e.preventDefault()}>
        <label className="field">League
          <select value={leagueId} onChange={e => setParams(e.target.value ? { league_id: e.target.value } : {}, { replace: true })}>
            <option value="">All leagues</option>
            {leagues.data?.map(l => <option key={l.league_id} value={l.league_id}>{l.league_name}</option>)}
          </select>
        </label>
      </form>

      {notice && <p className="notice notice-success" role="status">{notice}</p>}
      {teams.error && <p className="notice notice-error" role="alert">{teams.error}</p>}
      {teams.loading && !teams.data && <p className="loading">Loading teams…</p>}
      {teams.data && teams.data.length === 0 && (
        <section className="empty-state">
          <h2>No teams in this league yet</h2>
          <Link className="text-link" to={`/teams/new${query({ league: leagueId })}`}>Register the first one <span aria-hidden="true">→</span></Link>
        </section>
      )}
      {teams.data && teams.data.length > 0 && (
        <>
          <p className="result-count">{teams.data.length} team{teams.data.length === 1 ? '' : 's'}</p>
          <TeamTable teams={teams.data} />
        </>
      )}
    </main>
  )
}

export default Teams
