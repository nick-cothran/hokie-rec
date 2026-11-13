import { useState, type FormEvent } from 'react'
import { api, campusTime, useApi, type Facility, type TeamSummary } from '../api'
export default function GenerateSchedule({ leagueId, minimum, unavailableReason, onCreated }: { leagueId: string; minimum: number; unavailableReason?: string; onCreated: () => void }) {
  const facilities = useApi<Facility[]>('/api/admin/facilities')
  const teams = useApi<TeamSummary[]>(`/api/teams?league_id=${leagueId}`)
  const undersized = teams.data?.filter(team => team.status === 'active' && team.member_count < minimum) ?? []
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget, values = new FormData(form)
    if (!window.confirm(`Create a game for every pair of active teams? The league must not already have regular-season games.${undersized.length ? `\n\n${undersized.length} team(s) are below the minimum roster size.` : ''}`)) return
    setError(''); setNotice(''); setBusy(true)
    try {
      const result = await api<{ games_created: number }>(`/api/admin/leagues/${leagueId}/generate-schedule`, { method: 'POST', body: JSON.stringify({ facility_id: Number(values.get('facility')), start_time: campusTime(String(values.get('start'))).toISOString(), duration_minutes: Number(values.get('duration')), interval_minutes: Number(values.get('interval')) }) })
      setNotice(`Created ${result.games_created} games.`); form.reset(); onCreated()
    } catch (failure) { setError((failure as Error).message) } finally { setBusy(false) }
  }
  const activeCount = teams.data?.filter(team => team.status === 'active').length
  const reason = unavailableReason ?? (activeCount !== undefined && activeCount < 2 ? 'At least two active teams are needed to generate a schedule.' : activeCount !== undefined && activeCount > 32 ? 'Schedule generation supports up to 32 active teams.' : '')
  return <section className="schedule-tool-content"><h3>Generate a regular-season schedule</h3><p>Every active team plays each other once, using one facility and evenly spaced start times within the season dates.</p>
    {undersized.length > 0 && <p className="notice notice-info">Below the minimum of {minimum} active players: {undersized.map(team => `${team.team_name} (${team.member_count})`).join(', ')}. Confirm their rosters before game day.</p>}
    {(error || facilities.error || teams.error) && <p className="notice notice-error" role="alert">{error || facilities.error || teams.error}</p>}{notice && <p className="notice notice-success" role="status">{notice}</p>}
    {reason ? <p className="notice notice-info">{reason}</p> : teams.data && <form className="form-stack" onSubmit={submit}><label className="field">Facility<select name="facility" required defaultValue=""><option value="">Choose a facility</option>{facilities.data?.map(f => <option key={f.facility_id} value={f.facility_id}>{f.facility_name}</option>)}</select></label><label className="field">First game<input name="start" type="datetime-local" required /><small>Enter Blacksburg (Eastern) time.</small></label><label className="field">Game duration (minutes)<input name="duration" type="number" min="1" max="1440" defaultValue="60" required /></label><label className="field">Time between game starts (minutes)<input name="interval" type="number" min="1" max="10080" defaultValue="1440" required /></label><button className="button button-primary" disabled={busy || !leagueId}>{busy ? 'Creating…' : 'Generate schedule'}</button></form>}
  </section>
}
