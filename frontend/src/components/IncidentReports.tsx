import '../styles/IncidentReports.css'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, campusToday, formatDate, formatGameTime, query, useApi, type AdminPlayer, type Assignment, type IncidentReport } from '../api'
import { paginate } from '../pagination'
import { useAuth } from '../auth'
import Pagination from './Pagination'
import '../styles/ViewTabs.css'

const when = (iso: string) => formatGameTime(iso, { year: 'numeric' })

function matchName(report: IncidentReport) {
  return `${report.home_team_name ?? 'TBD'} vs ${report.away_team_name ?? 'TBD'}`
}

function FileIncidentForm({ assignments, onSubmitted }: {
  assignments: Assignment[]
  onSubmitted: () => void
}) {
  const [gameId, setGameId] = useState('')
  const [incidentType, setIncidentType] = useState('conduct')
  const [involvedPid, setInvolvedPid] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const games = assignments.filter(a => a.assignment_status !== 'declined' && a.status !== 'cancelled')

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      await api(`/api/games/${gameId}/incident-reports`, {
        method: 'POST',
        body: JSON.stringify({
          incident_type: incidentType,
          description,
          involved_user_pid: involvedPid.trim() || null,
        }),
      })
      setDescription('')
      setInvolvedPid('')
      onSubmitted()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="panel">
      <h2>File an incident report</h2>
      <p>Reports are private to officials and administrators. Select a game you are assigned to.</p>
      {games.length === 0 ? <p>You have no eligible game assignments.</p> : (
        <form className="form-stack incident-form" onSubmit={submit}>
          <label className="field">Game
            <select value={gameId} onChange={e => setGameId(e.target.value)} required>
              <option value="">Choose a game</option>
              {games.map(game => (
                <option key={game.game_id} value={game.game_id}>
                  {when(game.start_time)} · {game.league_name} · {game.home_team_name ?? 'TBD'} vs {game.away_team_name ?? 'TBD'}
                </option>
              ))}
            </select>
          </label>
          <label className="field">Incident type
            <select value={incidentType} onChange={e => setIncidentType(e.target.value)}>
              <option value="conduct">Conduct</option>
              <option value="sportsmanship">Sportsmanship</option>
              <option value="unsafe_play">Unsafe play</option>
              <option value="injury">Injury</option>
              <option value="eligibility">Eligibility</option>
              <option value="equipment">Equipment</option>
              <option value="late_arrival">Late arrival</option>
              <option value="facility">Facility</option>
              <option value="other">Other</option>
            </select>
          </label>
          <label className="field">Involved person's VT PID <small>Optional</small>
            <input value={involvedPid} onChange={e => setInvolvedPid(e.target.value)} maxLength={40} />
          </label>
          <label className="field">What happened?
            <textarea value={description} onChange={e => setDescription(e.target.value)} maxLength={4000} required rows={5} />
          </label>
          {error && <p className="notice notice-error" role="alert">{error}</p>}
          <button className="button button-primary" type="submit" disabled={saving || !gameId || !description.trim()}>
            {saving ? 'Submitting…' : 'Submit report'}
          </button>
        </form>
      )}
    </section>
  )
}

function IncidentList({ reports, isAdmin, onDecided }: {
  reports: IncidentReport[]
  isAdmin: boolean
  onDecided: () => void
}) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<number | null>(null)
  const [expanded, setExpanded] = useState(false)

  async function decide(report: IncidentReport, status: 'reviewed' | 'dismissed') {
    if (status === 'dismissed' && !window.confirm('Dismiss this incident report? This action cannot be undone.')) return
    setBusy(report.incident_id)
    setError('')
    try {
      await api(`/api/incidents/${report.incident_id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      })
      onDecided()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const openReports = isAdmin ? reports.filter(report => report.status === 'open') : reports
  const reviewedReports = isAdmin ? reports.filter(report => report.status !== 'open') : []

  function reportCards(items: IncidentReport[]) {
    return <ul className="incident-list">
      {items.map(report => (
        <li className="panel incident-card" key={report.incident_id}>
          <div className="incident-card-heading">
            <div>
              <p className="eyebrow">{report.incident_type.replaceAll('_', ' ')}</p>
              <h3>{matchName(report)}</h3>
            </div>
            <span className={`pill pill-${report.status}`}>{report.status}</span>
          </div>
          <p className="incident-description">{report.description}</p>
          <ul className="meta-list">
            <li><Link to={`/leagues/${report.league_id}`}>{report.league_name}</Link></li>
            <li>{when(report.start_time)} · {report.facility_name}</li>
            <li>Filed by {report.filed_by_first_name} {report.filed_by_last_name} on {when(report.filed_at)}</li>
            {report.involved_user_id !== null && <li>Involved: {report.involved_first_name} {report.involved_last_name}</li>}
            {report.reviewed_by_first_name && <li>Reviewed by {report.reviewed_by_first_name} {report.reviewed_by_last_name}</li>}
          </ul>
          {isAdmin && report.status === 'open' && <div className="form-row incident-actions">
            <button className="button button-primary button-small" type="button" disabled={busy !== null}
              onClick={() => decide(report, 'reviewed')}>{busy === report.incident_id ? 'Saving…' : 'Mark reviewed'}</button>
            <button className="button button-outline button-small" type="button" disabled={busy !== null}
              onClick={() => decide(report, 'dismissed')}>Dismiss</button>
          </div>}
        </li>
      ))}
    </ul>
  }

  return (
    <section>
      <div className="section-heading incident-list-heading">
        <h2>{isAdmin ? 'Open reports' : 'Reports you filed'}</h2>
        {isAdmin && <span className="incident-queue-count">{openReports.length}</span>}
      </div>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {openReports.length === 0 ? <p className="empty-state">{isAdmin ? 'No open incident reports need review.' : 'No incident reports to show.'}</p> : (
        <>
          {reportCards(isAdmin ? openReports : openReports.slice(0, expanded ? openReports.length : 3))}
          {!isAdmin && openReports.length > 3 && <button className="history-toggle incident-history-toggle" type="button" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>
            {expanded ? 'Show less' : `Show all ${openReports.length} reports`}
            <svg className={expanded ? 'history-chevron expanded' : 'history-chevron'} aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="m4 6 4 4 4-4" /></svg>
          </button>}
        </>
      )}
      {isAdmin && reviewedReports.length > 0 && <details className="reviewed-reports">
        <summary>Reviewed and dismissed reports <span className="pill">{reviewedReports.length}</span><svg aria-hidden="true" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="m4 6 4 4 4-4" /></svg></summary>
        {reportCards(reviewedReports)}
      </details>}
    </section>
  )
}

// The campus date `days` from today as "YYYY-MM-DD"; the server checks suspensions against the campus date
function campusDateAfter(days: number) {
  const [y, m, d] = campusToday().split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10)
}

function PlayerSuspensions() {
  const [search, setSearch] = useState('')
  const [term, setTerm] = useState('')
  const [suspendedUntil, setSuspendedUntil] = useState(() => campusDateAfter(7))
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<number | null>(null)
  const [page, setPage] = useState(1)
  const players = useApi<AdminPlayer[]>(`/api/admin/players${query({ q: term })}`)
  const playerPage = paginate(players.data ?? [], String(page))

  async function update(player: AdminPlayer, until: string | null) {
    setBusy(player.user_id)
    setError('')
    try {
      await api(`/api/admin/players/${player.user_id}/suspension`, {
        method: 'PATCH',
        body: JSON.stringify({ suspended_until: until }),
      })
      players.reload()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="admin-player-tools" aria-labelledby="player-suspensions-heading">
      <div className="page-intro"><h2 id="player-suspensions-heading">Player suspensions.</h2><p>Find a player, choose an end date, then use the action on their row.</p></div>
      <form className="filters suspension-filters" onSubmit={event => { event.preventDefault(); setTerm(search.trim()); setPage(1) }}>
        <label className="field suspension-player-field">Find a player
          <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Name or VT PID" />
        </label>
        <label className="field suspension-date-field">Suspension end date
          <input type="date" min={campusToday()} value={suspendedUntil}
            onChange={event => setSuspendedUntil(event.target.value)} />
        </label>
        <small className="suspension-date-help">Applied when you set or update a suspension.</small>
        <button className="button button-primary suspension-search-button" type="submit">Find players</button>
      </form>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {players.error && <p className="notice notice-error" role="alert">{players.error}</p>}
      {players.loading && !players.data && <p className="loading">Loading players…</p>}
      {players.data?.length === 0 && <p>No players found.</p>}
      {!!players.data?.length && (
        <>
          <p className="result-count">Showing {playerPage.start + 1}–{playerPage.end} of {players.data.length} players</p>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Player</th><th>VT PID</th><th>Status</th><th>Actions</th></tr></thead>
              <tbody>
                {playerPage.items.map(player => {
                  const suspended = !!player.suspended_until && player.suspended_until >= campusToday()
                  return <tr key={player.user_id}>
                    <td>{player.first_name} {player.last_name}</td>
                    <td>{player.vt_pid}</td>
                    <td>{!player.is_active ? <span className="pill">Inactive</span> : suspended
                      ? <span className="pill pill-suspended">Suspended through {formatDate(player.suspended_until!)}</span>
                      : <span className="pill pill-active">Active</span>}</td>
                    <td>{player.is_active && <div className="form-row suspension-actions">
                      <button className="button button-outline button-small" type="button" disabled={busy !== null || !suspendedUntil}
                        onClick={() => update(player, suspendedUntil)}>
                        {busy === player.user_id ? 'Saving…' : suspended ? 'Update end date' : 'Set suspension'}
                      </button>
                      {suspended && <button className="button button-danger button-small" type="button" disabled={busy !== null}
                        onClick={() => update(player, null)}>Lift suspension</button>}
                    </div>}</td>
                  </tr>
                })}
              </tbody>
            </table>
          </div>
          <Pagination page={playerPage.page} pageCount={playerPage.pageCount} onPageChange={setPage} />
        </>
      )}
      {players.data && players.data.length === 100 && <p className="result-count">Showing the first 100 matches. Search by a more specific name or PID.</p>}
    </section>
  )
}

function IncidentReports() {
  const { user, loading } = useAuth()
  const [adminTab, setAdminTab] = useState<'review' | 'suspensions'>('review')
  const isOfficial = user?.role === 'official'
  const isAdmin = user?.role === 'admin'
  const assignments = useApi<Assignment[]>(isOfficial ? '/api/me/assignments' : null)
  const reports = useApi<IncidentReport[]>(isOfficial || isAdmin ? '/api/incidents' : null)

  if (loading) {
    return <main className="content-page"><p className="loading">Checking your account…</p></main>
  }

  return (
    <main className="content-page incident-page">
      <div className="page-intro">
        <h1>Incident reports.</h1>
        <p>Record and review incidents connected to league games.</p>
      </div>
      {isAdmin && <nav className="view-tabs incident-admin-tabs" aria-label="Incident administration">
        <button type="button" className="view-tab" aria-pressed={adminTab === 'review'} onClick={() => setAdminTab('review')}>Review queue</button>
        <button type="button" className="view-tab" aria-pressed={adminTab === 'suspensions'} onClick={() => setAdminTab('suspensions')}>Player suspensions</button>
      </nav>}
      {!user && (
        <section className="empty-state">
          <h2>Sign in to continue</h2>
          <p>Incident reports are available to assigned officials and administrators.</p>
          <Link className="button button-primary" to="/sign-in?next=/incidents">Sign in</Link>
        </section>
      )}
      {user && !isOfficial && !isAdmin && (
        <p className="notice notice-info" role="status">Incident reports are available to assigned officials and administrators.</p>
      )}
      {isOfficial && assignments.loading && !assignments.data && <p className="loading">Loading your game assignments…</p>}
      {isOfficial && assignments.data && <FileIncidentForm assignments={assignments.data} onSubmitted={reports.reload} />}
      {isOfficial && assignments.error && <p className="notice notice-error" role="alert">{assignments.error}</p>}
      {(isOfficial || (isAdmin && adminTab === 'review')) && reports.error && <p className="notice notice-error" role="alert">{reports.error}</p>}
      {(isOfficial || (isAdmin && adminTab === 'review')) && reports.data && (
        <IncidentList reports={reports.data} isAdmin={isAdmin} onDecided={reports.reload} />
      )}
      {isAdmin && adminTab === 'suspensions' && <PlayerSuspensions />}
      {(isOfficial || (isAdmin && adminTab === 'review')) && reports.loading && !reports.data && <p className="loading">Loading incident reports…</p>}
    </main>
  )
}

export default IncidentReports
