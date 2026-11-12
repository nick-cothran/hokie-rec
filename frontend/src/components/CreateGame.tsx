import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, campusTime, query, useApi, type Facility, type League, type TeamSummary } from '../api'
import { useAuth } from '../auth'

export default function CreateGame() {
  const { user, loading } = useAuth()
  const navigate = useNavigate()
  const isAdmin = user?.role === 'admin'
  const leagues = useApi<League[]>(isAdmin ? '/api/leagues' : null)
  const facilities = useApi<Facility[]>(isAdmin ? '/api/admin/facilities' : null)
  const [league, setLeague] = useState('')
  const teams = useApi<TeamSummary[]>(isAdmin && league ? `/api/teams${query({ league_id: league })}` : null)
  const [home, setHome] = useState('')
  const [away, setAway] = useState('')
  const [facility, setFacility] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setError('')
    const startDate = campusTime(start), endDate = campusTime(end)
    if (!Number.isFinite(startDate.getTime()) || !Number.isFinite(endDate.getTime()) || endDate <= startDate) {
      setError('Choose a valid start time and an end time after it.')
      return
    }
    setBusy(true)
    try {
      await api('/api/admin/games', { method: 'POST', body: JSON.stringify({
        league_id: Number(league), facility_id: Number(facility), home_team_id: Number(home), away_team_id: Number(away),
        start_time: startDate.toISOString(), end_time: endDate.toISOString(),
      }) })
      navigate(`/schedule?league=${league}`, { state: { notice: 'Game scheduled successfully.' } })
    } catch (failure) { setError((failure as Error).message) }
    finally { setBusy(false) }
  }

  if (loading) return <main className="content-page"><p>Checking your session…</p></main>
  if (!isAdmin) return <main className="content-page"><section className="empty-state"><h1>Administrators only</h1><p>Sign in as an administrator to schedule a game.</p>{!user && <Link className="button button-primary" to="/sign-in?next=%2Fadmin%2Fgames%2Fnew">Sign in</Link>}</section></main>

  return <main className="content-page detail-page">
    <Link className="back-link" to="/schedule">← Schedule</Link>
    <div className="page-intro"><p className="eyebrow">Administration</p><h1>Schedule a game.</h1><p>Choose the teams, facility, and time for a regular-season game.</p></div>
    <section className="panel">
      {(leagues.error || facilities.error || teams.error) && <p className="notice notice-error" role="alert">{leagues.error || facilities.error || teams.error}</p>}
      <form className="form-stack" onSubmit={submit}>
        <label className="field">League<select value={league} required disabled={busy || leagues.loading} onChange={e => { setLeague(e.target.value); setHome(''); setAway('') }}><option value="">Choose a league</option>{leagues.data?.map(l => <option key={l.league_id} value={l.league_id}>{l.league_name}</option>)}</select></label>
        <label className="field">Home team<select value={home} required disabled={busy || !league || teams.loading} onChange={e => setHome(e.target.value)}><option value="">Choose a team</option>{teams.data?.filter(t => t.status === 'active' && String(t.team_id) !== away).map(t => <option key={t.team_id} value={t.team_id}>{t.team_name}</option>)}</select></label>
        <label className="field">Away team<select value={away} required disabled={busy || !league || teams.loading} onChange={e => setAway(e.target.value)}><option value="">Choose a team</option>{teams.data?.filter(t => t.status === 'active' && String(t.team_id) !== home).map(t => <option key={t.team_id} value={t.team_id}>{t.team_name}</option>)}</select></label>
        {league && teams.data && teams.data.filter(t => t.status === 'active').length < 2 && <p className="notice notice-info">This league needs at least two active teams to schedule a game.</p>}
        <label className="field">Facility<select value={facility} required disabled={busy || facilities.loading} onChange={e => setFacility(e.target.value)}><option value="">Choose a facility</option>{facilities.data?.map(f => <option key={f.facility_id} value={f.facility_id}>{f.facility_name} — {f.location}</option>)}</select></label>
        <label className="field">Start<input type="datetime-local" required value={start} disabled={busy} onChange={e => setStart(e.target.value)} /></label>
        <label className="field">End<input type="datetime-local" required value={end} disabled={busy} onChange={e => setEnd(e.target.value)} /><small>Enter Blacksburg (Eastern) times.</small></label>
        {error && <p className="notice notice-error" role="alert">{error}</p>}
        <div className="form-row"><button className="button button-primary" disabled={busy || !league || !home || !away || !facility || !start || !end}>{busy ? 'Scheduling…' : 'Schedule game'}</button><Link className="button button-outline" to="/schedule">Cancel</Link></div>
      </form>
    </section>
  </main>
}
