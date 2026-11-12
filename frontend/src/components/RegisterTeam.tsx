import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, useApi, type League } from '../api'
import { fullName, useAuth } from '../auth'

// S2: register a team; the signed-in player becomes its captain
function RegisterTeam() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { user, loading } = useAuth()
  const leagues = useApi<League[]>('/api/leagues')

  const [leagueId, setLeagueId] = useState(params.get('league') ?? '')
  const [teamName, setTeamName] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const open = leagues.data?.filter(l => l.registration_open) ?? []
  const terms = [...new Set(open.map(l => l.term))]

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!user || user.role !== 'player' || loading || saving) return
    setSaving(true)
    setError('')
    try {
      const team = await api<{ team_id: number }>('/api/teams', {
        method: 'POST',
        body: JSON.stringify({ league_id: Number(leagueId), team_name: teamName }),
      })
      navigate(`/teams/${team.team_id}`, { state: { notice: `“${teamName.trim()}” is registered, with you as captain.` } })
    } catch (e) {
      setError((e as Error).message)
      setSaving(false)
    }
  }

  return (
    <main className="content-page detail-page">
      <Link className="back-link" to="/teams">← Team directory</Link>
      <div className="page-intro">
        <p className="eyebrow">New team</p>
        <h1>Register a team.</h1>
        <p>Pick a league and a name. You'll be the captain and the first player on the roster.</p>
      </div>

      <section className="panel">
        <form className="form-stack" onSubmit={handleSubmit}>
          {!user && (
            <p className="notice notice-info"><Link to={`/sign-in?next=${encodeURIComponent('/teams/new' + (params.size ? '?' + params.toString() : ''))}`}>Sign in</Link> before registering a team.</p>
          )}
          {user && user.role !== 'player' && (
            <p className="notice notice-info">You're signed in as {fullName(user)}, who is {user.role === 'admin' ? 'an' : 'a'} {user.role}. Only players can register teams.</p>
          )}
          {leagues.data && open.length === 0 && <p className="notice notice-info">No leagues are open for registration right now.</p>}
          <label className="field">League
            <select value={leagueId} onChange={e => setLeagueId(e.target.value)} required disabled={!leagues.data}>
              <option value="">{leagues.loading ? 'Loading leagues…' : 'Choose a league'}</option>
              {terms.map(term => (
                <optgroup key={term} label={term}>
                  {open.filter(l => l.term === term).map(l => (
                    <option key={l.league_id} value={l.league_id}>{l.league_name}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
          <label className="field">Team name
            <input value={teamName} onChange={e => setTeamName(e.target.value)} maxLength={60} required placeholder="e.g. Turkey Trotters" />
            <small>Up to 60 characters. Names must be unique within a league.</small>
          </label>
          <label className="field">Captain
            <input value={user ? fullName(user) : 'Not signed in'} readOnly disabled />
          </label>
          {leagues.error && <p className="notice notice-error" role="alert">{leagues.error}</p>}
          {error && <p className="notice notice-error" role="alert">{error}</p>}
          <div className="form-row">
            <button className="button button-primary" type="submit" disabled={loading || !user || user.role !== 'player' || saving}>{saving ? 'Registering…' : 'Register team'}</button>
            <Link className="button button-outline" to="/teams">Cancel</Link>
          </div>
        </form>
      </section>
    </main>
  )
}

export default RegisterTeam
