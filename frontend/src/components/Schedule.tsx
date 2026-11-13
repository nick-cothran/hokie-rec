import '../styles/Schedule.css'
import '../styles/Teams.css'
import { useState, type FormEvent } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { api, campusTime, forfeitLabel, formatDate, formatGameTime as when, gameRound as round, query, useApi, type Assignment, type Game, type League, type MyGames, type Official } from '../api'
import { useAuth } from '../auth'
import GenerateSchedule from './GenerateSchedule'

function result(g: Game) {
  if (g.forfeit_team_id !== null) return forfeitLabel(g, g.forfeit_team_id)
  if (g.home_score !== null && g.away_score !== null) return `${g.home_score}–${g.away_score}`
  if (g.status === 'scheduled' && new Date(g.end_time).getTime() < Date.now()) return 'Awaiting result'
  return g.status
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
  const needsAction = assignments.data?.filter(a => a.can_respond || (a.status === 'scheduled' && a.assignment_status !== 'declined' && a.has_ended && a.home_team_id !== null && a.away_team_id !== null)) ?? []
  const upcoming = assignments.data?.filter(a => !needsAction.includes(a) && a.status === 'scheduled' && a.assignment_status !== 'declined' && !a.has_ended) ?? []
  const other = assignments.data?.filter(a => !needsAction.includes(a) && !upcoming.includes(a)).slice().sort((a, b) => new Date(b.start_time).getTime() - new Date(a.start_time).getTime()) ?? []

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

  function list(items: Assignment[]) {
    return <ul className="invite-list assignment-list">
        {items.map(a => (
          <li key={a.assignment_id}>
            <div>
              <strong><TeamLink id={a.home_team_id} name={a.home_team_name} /> vs <TeamLink id={a.away_team_id} name={a.away_team_name} /></strong>
              <span className="invite-meta">
                {when(a.start_time)} · {a.facility_name} · {a.league_name} · {a.position} · <span className={`pill pill-${a.assignment_status}`}>{a.assignment_status}</span>{a.status === 'cancelled' && <> · Game cancelled</>}
              </span>
            </div>
            {a.assignment_status !== 'declined' && a.status !== 'cancelled' && a.home_team_id !== null && a.away_team_id !== null && a.has_ended && (
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
  }

  return (
    <section className="panel invitations official-assignments" aria-labelledby="assignments-heading">
      <h2 id="assignments-heading">Your assignments</h2>
      {(error || assignments.error) && <p className="notice notice-error" role="alert">{error || assignments.error}</p>}
      {assignments.loading && !assignments.data && <p role="status">Loading assignments…</p>}
      {assignments.data?.length === 0 && <p>No assignments yet.</p>}
      {!!assignments.data?.length && <>
        <h3>Needs action</h3>
        {needsAction.length ? list(needsAction) : <p>No assignments need your attention.</p>}
        <h3>Upcoming and in progress</h3>
        {upcoming.length ? list(upcoming) : <p>No other upcoming or in-progress assignments.</p>}
        {!!other.length && <details className="assignment-history"><summary>Past, declined and cancelled ({other.length})</summary>{list(other)}</details>}
      </>}
    </section>
  )
}

function AdminAssignmentForm({ games }: { games: Game[] }) {
  const officials = useApi<Official[]>('/api/admin/officials')
  const [gameId, setGameId] = useState('')
  const [officialId, setOfficialId] = useState('')
  const [position, setPosition] = useState('referee')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState(false)
  const [revision, setRevision] = useState(0)
  const league = games[0]?.league_id
  const coverage = useApi<{ game_id: number; assigned_count: number }[]>(league ? `/api/admin/games/coverage?league_id=${league}` : null)
  const assignable = games.filter(game => game.status === 'scheduled' || game.status === 'completed')

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError('')
    setNotice('')
    try {
      await api('/api/admin/assignments', {
        method: 'POST',
        body: JSON.stringify({ game_id: Number(gameId), official_id: Number(officialId), position }),
      })
      setNotice('Assignment created.')
      setOfficialId('')
      setRevision(value => value + 1)
      coverage.reload()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="panel" aria-labelledby="admin-assignments-heading">
      <h2 id="admin-assignments-heading">Create an officiating assignment</h2>
      <p>For a completed game, assign an official if another result or correction is needed.</p>
      {coverage.error && <p className="notice notice-error" role="alert">{coverage.error}</p>}
      {coverage.data && <p>{coverage.data.filter(row => row.assigned_count === 0).length} scheduled {coverage.data.filter(row => row.assigned_count === 0).length === 1 ? 'game has' : 'games have'} no official assigned.</p>}
      {officials.error && <p className="notice notice-error" role="alert">{officials.error}</p>}
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {notice && <p className="notice notice-success" role="status">{notice}</p>}
      {assignable.length === 0 ? <p>No scheduled or completed games in this league.</p> : officials.data?.length === 0 ? (
        <p>No active officials are available.</p>
      ) : (
        <form className="form-row admin-assignment-form" onSubmit={submit}>
          <label className="field">Game
            <select value={gameId} onChange={e => setGameId(e.target.value)} required>
              <option value="">Choose a game</option>
              {assignable.map(game => (
                <option key={game.game_id} value={game.game_id}>
                {when(game.start_time)} · {game.facility_name} · {game.home_team_name ?? 'TBD'} vs {game.away_team_name ?? 'TBD'}{game.status === 'completed' ? ' · Completed (correction)' : coverage.data?.some(row => row.game_id === game.game_id && row.assigned_count === 0) ? ' · No official' : ''}
                </option>
              ))}
            </select>
          </label>
          <label className="field">Official
            <select value={officialId} onChange={e => setOfficialId(e.target.value)} required>
              <option value="">Choose an official</option>
              {officials.data?.map(official => (
                <option key={official.user_id} value={official.user_id}>
                  {official.first_name} {official.last_name} · {official.vt_pid}
                </option>
              ))}
            </select>
          </label>
          <label className="field">Position
            <select value={position} onChange={e => setPosition(e.target.value)}>
              <option value="referee">Referee</option>
              <option value="scorekeeper">Scorekeeper</option>
            </select>
          </label>
          <button className="button button-primary" type="submit" disabled={saving || officials.loading || !gameId || !officialId}>
            {saving ? 'Creating…' : 'Assign official'}
          </button>
        </form>
      )}
      {gameId && <AssignmentDetails key={`${gameId}-${revision}`} gameId={gameId} onChanged={coverage.reload} />}
    </section>
  )
}

type GameAssignment = { assignment_id: number; first_name: string; last_name: string; vt_pid: string; position: string; status: string }

function AssignmentDetails({ gameId, onChanged }: { gameId: string; onChanged: () => void }) {
  const assignments = useApi<GameAssignment[]>(`/api/admin/games/${gameId}/assignments`)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function remove(assignment: GameAssignment) {
    if (!window.confirm(`Remove ${assignment.first_name} ${assignment.last_name}'s assignment?`)) return
    setBusy(true)
    setError('')
    try {
      await api(`/api/admin/assignments/${assignment.assignment_id}`, { method: 'DELETE' })
      assignments.reload()
      onChanged()
    } catch (failure) { setError((failure as Error).message) }
    finally { setBusy(false) }
  }
  return <div className="assignment-details">
    <h3>Officials for this game</h3>
    {(error || assignments.error) && <p className="notice notice-error" role="alert">{error || assignments.error}</p>}
    {assignments.loading && <p>Loading assignments…</p>}
    {!assignments.loading && !assignments.error && assignments.data?.length === 0 && <p>No officials assigned yet.</p>}
    <ul className="invite-list">{assignments.data?.map(assignment => <li key={assignment.assignment_id}>
      <span>{assignment.first_name} {assignment.last_name} · {assignment.position} · {assignment.status}</span>
      <button className="button button-outline button-small" type="button" disabled={busy} onClick={() => remove(assignment)}>Remove</button>
    </li>)}</ul>
  </div>
}

function ManageGame({ games, onChanged }: { games: Game[]; onChanged: () => void }) {
  const facilities = useApi<{ facility_id: number; facility_name: string }[]>('/api/admin/facilities')
  const [gameId, setGameId] = useState('')
  const [facility, setFacility] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [now] = useState(() => Date.now())
  const available = games.filter(game => game.status === 'scheduled' && game.playoff_round === null && new Date(game.start_time).getTime() > now)
  async function perform(action: 'reschedule' | 'cancel') {
    if (busy || !gameId) return
    if (action === 'cancel' && !window.confirm('Cancel this game? It will remain on the schedule as cancelled.')) return
    if (action === 'reschedule' && (!facility || !start || !end || campusTime(end) <= campusTime(start))) {
      setError('Choose a facility and valid start and end times.')
      return
    }
    setBusy(true); setError(''); setNotice('')
    try {
      await api(`/api/admin/games/${gameId}/${action === 'cancel' ? 'cancel' : 'schedule'}`, action === 'cancel'
        ? { method: 'POST' }
        : { method: 'PUT', body: JSON.stringify({ facility_id: Number(facility), start_time: campusTime(start).toISOString(), end_time: campusTime(end).toISOString() }) })
      setNotice(action === 'cancel' ? 'Game cancelled.' : 'Game rescheduled. Accepted officials must respond again.')
      setGameId(''); setFacility(''); setStart(''); setEnd(''); onChanged()
    } catch (failure) { setError((failure as Error).message) }
    finally { setBusy(false) }
  }
  return <section className="panel"><h2>Manage scheduled games</h2>
    <p>Change the time or facility, or cancel an upcoming regular-season game. Manage playoff games through the league bracket.</p>
    {facilities.error && <p className="notice notice-error" role="alert">{facilities.error}</p>}
    {error && <p className="notice notice-error" role="alert">{error}</p>}
    {notice && <p className="notice notice-success" role="status">{notice}</p>}
    {available.length === 0 ? <p>No upcoming games in this league.</p> : <div className="form-stack">
      <label className="field">Game<select value={gameId} onChange={event => setGameId(event.target.value)}><option value="">Choose a game</option>{available.map(game => <option key={game.game_id} value={game.game_id}>{when(game.start_time)} · {game.home_team_name ?? 'TBD'} vs {game.away_team_name ?? 'TBD'}</option>)}</select></label>
      {gameId && <>
        <label className="field">New facility<select value={facility} onChange={event => setFacility(event.target.value)}><option value="">Choose a facility</option>{facilities.data?.map(item => <option key={item.facility_id} value={item.facility_id}>{item.facility_name}</option>)}</select></label>
        <label className="field">New start<input type="datetime-local" value={start} onChange={event => setStart(event.target.value)} /></label>
        <label className="field">New end<input type="datetime-local" value={end} onChange={event => setEnd(event.target.value)} /><small>Enter Blacksburg (Eastern) times.</small></label>
        <div className="form-row"><button className="button button-primary" type="button" disabled={busy} onClick={() => perform('reschedule')}>Reschedule</button><button className="button button-danger" type="button" disabled={busy} onClick={() => perform('cancel')}>Cancel game</button></div>
      </>}
    </div>}
  </section>
}

function Schedule() {
  const { user } = useAuth()
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const [coverageRevision, setCoverageRevision] = useState(0)
  const leagues = useApi<League[]>('/api/leagues')
  const leagueId = params.get('league') ?? String(leagues.data?.find(l => l.team_count > 0)?.league_id ?? '')
  const teamId = params.get('team') ?? ''
  const selectedLeague = leagues.data?.find(item => String(item.league_id) === leagueId)
  const games = useApi<Game[]>(leagueId ? `/api/games${query({ league_id: leagueId })}` : null)
  const visibleGames = teamId ? games.data?.filter(game => String(game.home_team_id) === teamId || String(game.away_team_id) === teamId) : games.data
  const generatorReason = games.data?.some(game => game.playoff_round !== null)
    ? 'A playoff bracket already exists. Remove the unplayed bracket before generating regular-season games.'
    : games.data?.some(game => game.playoff_round === null && game.status !== 'cancelled')
      ? 'This league already has regular-season games. Schedule additional games individually.' : undefined
  function refreshGames() { games.reload(); setCoverageRevision(value => value + 1) }

  return (
    <main className="content-page schedule-page">
      <div className="page-intro">
        <p className="eyebrow">Game day</p>
        <div className="intro-row">
          <div><h1>Schedules & scores.</h1><p>Know where to be and who you’re playing.</p></div>
        </div>
      </div>

      {location.state?.notice && <p className="notice notice-success" role="status">{location.state.notice}</p>}
      {user?.role === 'admin' && <p className="form-row"><Link className="button button-primary" to="/admin/games/new">Schedule a game</Link>{leagueId && <a className="text-link" href="#manage-schedule-heading">Manage league schedule ↓</a>}</p>}

      {user?.role === 'official' && <Assignments />}
      {user?.role === 'player' && <YourGames key={user.user_id} />}
      <form className="filters" onSubmit={e => e.preventDefault()}>
        <label className="field">League
          <select value={leagueId} onChange={e => setParams({ league: e.target.value }, { replace: true })}>
            {leagues.data?.map(l => <option key={l.league_id} value={l.league_id}>{l.league_name}</option>)}
          </select>
        </label>
      </form>
      {user?.role === 'admin' && selectedLeague && <p>Regular-season dates: {formatDate(selectedLeague.start_date)} – {formatDate(selectedLeague.end_date)}.</p>}
      <section>
        <h2>League schedule</h2>
        {teamId && <p>Showing games for the selected team. <Link className="text-link" to={`/schedule?league=${leagueId}`}>Show all league games</Link></p>}
        {(leagues.error || games.error) && <p className="notice notice-error" role="alert">{leagues.error || games.error}</p>}
        {games.loading && !games.data && <p className="loading">Loading games…</p>}
        {visibleGames?.length === 0 && (
          <section className="empty-state" aria-live="polite">
            <h2>No games scheduled</h2>
            <p>{teamId ? 'No games scheduled for this team yet.' : 'No games scheduled for this league yet.'}</p>
          </section>
        )}
        {!!visibleGames?.length && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr><th>When</th><th>Where</th><th>Home</th><th>Away</th><th>Round</th><th>Result</th></tr>
              </thead>
              <tbody>
                {visibleGames.map(g => (
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
      {user?.role === 'admin' && leagueId && <section className="admin-schedule-tools" aria-labelledby="manage-schedule-heading">
        <h2 id="manage-schedule-heading">Manage this league</h2>
        <details className="schedule-tool"><summary>Generate a regular-season schedule</summary>
          {games.error ? <p className="notice notice-error">{games.error}</p> : games.data ? <GenerateSchedule key={leagueId} leagueId={leagueId} minimum={selectedLeague?.min_roster_size ?? 0} unavailableReason={generatorReason} onCreated={refreshGames} /> : <p>Loading league schedule…</p>}
        </details>
        <details className="schedule-tool"><summary>Assign officials</summary>
          {games.data && <AdminAssignmentForm key={`${leagueId}-${coverageRevision}`} games={games.data} />}
        </details>
        <details className="schedule-tool"><summary>Reschedule or cancel games</summary>
          {games.data && <ManageGame key={leagueId} games={games.data} onChanged={refreshGames} />}
        </details>
      </section>}
    </main>
  )
}

export default Schedule
