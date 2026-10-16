import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, useApi, type League } from '../api'
import { fullName, useActingUser } from '../actingUser'

// S2: register a team; the acting user becomes its captain
function RegisterTeam() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { user } = useActingUser()
  const leagues = useApi<League[]>('/api/leagues')

  const [leagueId, setLeagueId] = useState(params.get('league') ?? '')
  const [teamName, setTeamName] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const terms = [...new Set(leagues.data?.map(l => l.term))]

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!user) return
    setSaving(true)
    setError('')
    try {
      const team = await api<{ team_id: number }>('/api/teams', {
        method: 'POST',
        body: JSON.stringify({ league_id: Number(leagueId), team_name: teamName, user_id: user.user_id }),
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
            <p className="notice notice-info"><Link to="/sign-in">Choose who you're acting as</Link> before registering a team.</p>
          )}
          {user && user.role !== 'player' && (
            <p className="notice notice-info">You're acting as {fullName(user)}, who is {user.role === 'admin' ? 'an' : 'a'} {user.role}. Only players can register teams.</p>
          )}
          <label className="field">League
            <select value={leagueId} onChange={e => setLeagueId(e.target.value)} required disabled={!leagues.data}>
              <option value="">{leagues.loading ? 'Loading leagues…' : 'Choose a league'}</option>
              {terms.map(term => (
                <optgroup key={term} label={term}>
                  {leagues.data?.filter(l => l.term === term).map(l => (
                    <option key={l.league_id} value={l.league_id}>{l.league_name} ({l.skill_level})</option>
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
            <input value={user ? fullName(user) : 'No user chosen'} readOnly disabled />
          </label>
          {leagues.error && <p className="notice notice-error" role="alert">{leagues.error}</p>}
          {error && <p className="notice notice-error" role="alert">{error}</p>}
          <div className="form-row">
            <button className="button button-primary" type="submit" disabled={!user || saving}>{saving ? 'Registering…' : 'Register team'}</button>
            <Link className="button button-outline" to="/teams">Cancel</Link>
          </div>
        </form>
      </section>
    </main>
  )
}

export default RegisterTeam
