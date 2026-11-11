import '../styles/IncidentReports.css'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, useApi, type Assignment, type IncidentReport } from '../api'
import { useAuth } from '../auth'

function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    timeZone: 'America/New_York', dateStyle: 'medium', timeStyle: 'short',
  })
}

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

  return (
    <section>
      <div className="section-heading"><h2>{isAdmin ? 'Review queue' : 'Reports you filed'}</h2></div>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {reports.length === 0 ? <p className="empty-state">No incident reports to show.</p> : (
        <ul className="incident-list">
          {reports.map(report => (
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
                {report.involved_user_id !== null && (
                  <li>Involved: {report.involved_first_name} {report.involved_last_name}</li>
                )}
                {report.reviewed_by_first_name && (
                  <li>Reviewed by {report.reviewed_by_first_name} {report.reviewed_by_last_name}</li>
                )}
              </ul>
              {isAdmin && report.status === 'open' && (
                <div className="form-row incident-actions">
                  <button className="button button-primary button-small" type="button" disabled={busy !== null}
                    onClick={() => decide(report, 'reviewed')}>{busy === report.incident_id ? 'Saving…' : 'Mark reviewed'}</button>
                  <button className="button button-outline button-small" type="button" disabled={busy !== null}
                    onClick={() => decide(report, 'dismissed')}>Dismiss</button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function IncidentReports() {
  const { user, loading } = useAuth()
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
        <p className="eyebrow">Game-day documentation</p>
        <h1>Incident reports.</h1>
        <p>Record and review incidents connected to league games.</p>
      </div>
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
      {(assignments.error || reports.error) && (
        <p className="notice notice-error" role="alert">{assignments.error || reports.error}</p>
      )}
      {(isOfficial || isAdmin) && reports.data && (
        <IncidentList reports={reports.data} isAdmin={isAdmin} onDecided={reports.reload} />
      )}
      {reports.loading && !reports.data && <p className="loading">Loading incident reports…</p>}
    </main>
  )
}

export default IncidentReports
