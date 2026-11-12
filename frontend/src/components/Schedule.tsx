import '../styles/Schedule.css'
import '../styles/Teams.css'
import { useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { api, formatGameTime as when, query, useApi, type Assignment, type Game, type League, type MyGames } from '../api'
import { useAuth } from '../auth'

function result(g: Game) {
  if (g.forfeit_team_id !== null) {
    return `Forfeit: ${g.forfeit_team_id === g.home_team_id ? g.home_team_name : g.away_team_name}`
  }
  if (g.home_score !== null && g.away_score !== null) return `${g.home_score}–${g.away_score}`
  return g.status
}

function round(g: Game) {
  if (g.playoff_round === null) return ''
  return g.next_game_id === null ? 'Final' : `Playoff round ${g.playoff_round}`
}

function TeamLink({ id, name }: { id: number | null; name: string | null }) {
  return id === null ? <span>TBD</span> : <Link to={`/teams/${id}`}>{name}</Link>
}

function PersonalGameList({ games }: { games: Game[] }) {
  return <ul className="invite-list personal-games-list">
    {games.map(game => <li key={game.game_id}>
      <div>
        <strong><TeamLink id={game.home_team_id} name={game.home_team_name} /> vs <TeamLink id={game.away_team_id} name={game.away_team_name} /></strong>
        <span className="invite-meta">{when(game.start_time)} · {game.facility_name} · {game.league_name}{round(game) ? ` · ${round(game)}` : ''}</span>
      </div>
      <span className="pill">{result(game)}</span>
    </li>)}
  </ul>
}

function YourGames() {
  const games = useApi<MyGames>('/api/me/games')
  return <section className="panel personal-games" aria-labelledby="your-games-heading">
    <h2 id="your-games-heading">Your games</h2>
    <p>Games for teams where you are currently an active player.</p>
    {games.loading && <p role="status">Loading your games…</p>}
    {games.error && <p className="notice notice-error" role="alert">{games.error}</p>}
    {!games.loading && !games.error && games.data && <>
      <h3>Upcoming and in progress</h3>
      {games.data.upcoming.length ? <PersonalGameList games={games.data.upcoming} /> : <p>No upcoming games for your teams.</p>}
      <h3>Recent results</h3>
      {games.data.recent.length ? <PersonalGameList games={games.data.recent} /> : <p>No recent results for your teams.</p>}
    </>}
  </section>
}

// The signed-in official's games: accept or decline while pending and before kickoff
function Assignments() {
  const assignments = useApi<Assignment[]>('/api/me/assignments')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function answer(a: Assignment, action: 'accept' | 'decline') {
    setBusy(true)
    setError('')
    try {
      await api(`/api/assignments/${a.assignment_id}/${action}`, { method: 'POST' })
    } catch (e) {
      setError((e as Error).message)
    }
    assignments.reload()
    setBusy(false)
  }

  return (
    <section className="panel invitations" aria-labelledby="assignments-heading">
      <h2 id="assignments-heading">Your assignments</h2>
      {(error || assignments.error) && <p className="notice notice-error" role="alert">{error || assignments.error}</p>}
      {assignments.data?.length === 0 && <p>No assignments yet.</p>}
      <ul className="invite-list">
        {assignments.data?.map(a => (
          <li key={a.assignment_id}>
            <div>
              <strong><TeamLink id={a.home_team_id} name={a.home_team_name} /> vs <TeamLink id={a.away_team_id} name={a.away_team_name} /></strong>
              <span className="invite-meta">
                {when(a.start_time)} · {a.facility_name} · {a.league_name} · {a.position} · <span className={`pill pill-${a.assignment_status}`}>{a.assignment_status}</span>
              </span>
            </div>
            {a.assignment_status !== 'declined' && a.home_team_id !== null && a.away_team_id !== null && a.has_ended && (
              <Link className={`button button-small ${a.status === 'completed' ? 'button-outline' : 'button-primary'}`} to={`/games/${a.game_id}/score`}>
                {a.status === 'completed' ? 'View result' : 'Enter result'}
              </Link>
            )}
            {a.can_respond && (
              <div className="form-row">
                <button className="button button-primary button-small" type="button" disabled={busy} onClick={() => answer(a, 'accept')}>Accept</button>
                <button className="button button-outline button-small" type="button" disabled={busy} onClick={() => answer(a, 'decline')}>Decline</button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

function Schedule() {
  const { user } = useAuth()
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const leagues = useApi<League[]>('/api/leagues')
  const leagueId = params.get('league') ?? String(leagues.data?.find(l => l.team_count > 0)?.league_id ?? '')
  const games = useApi<Game[]>(leagueId ? `/api/games${query({ league_id: leagueId })}` : null)

  return (
    <main className="content-page schedule-page">
      <div className="page-intro">
        <p className="eyebrow">Game day</p>
        <div className="intro-row">
          <div><h1>Schedules & scores.</h1><p>Know where to be and who you’re playing.</p></div>
        </div>
      </div>

      {location.state?.notice && <p className="notice notice-success" role="status">{location.state.notice}</p>}
      {user?.role === 'admin' && <p><Link className="button button-primary" to="/admin/games/new">Schedule a game</Link></p>}

      {user?.role === 'official' && <Assignments />}
      {user?.role === 'player' && <YourGames key={user.user_id} />}

      <section>
        <h2>League schedule</h2>
        <form className="filters" onSubmit={e => e.preventDefault()}>
          <label className="field">League
            <select value={leagueId} onChange={e => setParams({ league: e.target.value }, { replace: true })}>
              {leagues.data?.map(l => <option key={l.league_id} value={l.league_id}>{l.league_name}</option>)}
            </select>
          </label>
        </form>
        {(leagues.error || games.error) && <p className="notice notice-error" role="alert">{leagues.error || games.error}</p>}
        {games.loading && !games.data && <p className="loading">Loading games…</p>}
        {games.data?.length === 0 && (
          <section className="empty-state" aria-live="polite">
            <h2>No games scheduled</h2>
            <p>No games scheduled for this league yet.</p>
          </section>
        )}
        {!!games.data?.length && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr><th>When</th><th>Where</th><th>Home</th><th>Away</th><th>Round</th><th>Result</th></tr>
              </thead>
              <tbody>
                {games.data.map(g => (
                  <tr key={g.game_id}>
                    <td>{when(g.start_time)}</td>
                    <td>{g.facility_name}</td>
                    <td><TeamLink id={g.home_team_id} name={g.home_team_name} /></td>
                    <td><TeamLink id={g.away_team_id} name={g.away_team_name} /></td>
                    <td>{round(g)}</td>
                    <td>{user?.role === 'admin' && g.status === 'completed' ? <Link to={`/games/${g.game_id}/score`}>{result(g)}</Link> : result(g)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  )
}

export default Schedule
