import '../styles/Teams.css'
import { useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { api, formatDate, query, useApi, type Invite, type League, type TeamSummary } from '../api'
import { useAuth } from '../auth'
import TeamTable from './TeamTable'

// The signed-in player's pending invites. Hidden when there are none.
function Invitations({ onAnswered }: { onAnswered: (message: string) => void }) {
  const { user } = useAuth()
  const invites = useApi<Invite[]>(user ? '/api/me/invites' : null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function answer(invite: Invite, action: 'accept' | 'decline') {
    setBusy(true)
    setError('')
    try {
      await api(`/api/teams/${invite.team_id}/invite/${action}`, { method: 'POST' })
      onAnswered(action === 'accept' ? `You joined ${invite.team_name}.` : `Declined the invite to ${invite.team_name}.`)
      invites.reload()
    } catch (e) {
      setError((e as Error).message)
    }
    setBusy(false)
  }

  if (!invites.data?.length && !error) return null
  return (
    <section className="panel invitations" aria-labelledby="invitations-heading">
      <h2 id="invitations-heading">Your invitations</h2>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      <ul className="invite-list">
        {invites.data?.map(invite => {
          const full = invite.active_count >= invite.max_roster_size
          return (
            <li key={invite.team_id}>
              <div>
                <Link className="text-link" to={`/teams/${invite.team_id}`}><strong>{invite.team_name}</strong></Link>
                <span className="invite-meta">
                  {invite.league_name} · Captain {invite.captain_first_name} {invite.captain_last_name} · {invite.active_count} / {invite.max_roster_size} players · {invite.roster_locked ? 'Roster locked' : `Roster locks ${formatDate(invite.roster_lock_date)}`}
                </span>
              </div>
              <div className="form-row">
                <button className="button button-primary button-small" type="button" disabled={busy || invite.roster_locked || full}
                  title={invite.roster_locked ? 'The roster is locked.' : full ? 'This team is full.' : undefined}
                  onClick={() => answer(invite, 'accept')}>Accept</button>
                <button className="button button-outline button-small" type="button" disabled={busy}
                  onClick={() => answer(invite, 'decline')}>Decline</button>
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function Teams() {
  const [params, setParams] = useSearchParams()
  const routeNotice: string | undefined = useLocation().state?.notice
  const [answered, setAnswered] = useState('')
  const notice = answered || routeNotice
  const leagueId = params.get('league_id') ?? ''

  const leagues = useApi<League[]>('/api/leagues')
  const teams = useApi<TeamSummary[]>(`/api/teams${query({ league_id: leagueId })}`)

  return (
    <main className="content-page teams-page">
      <div className="page-intro">
        <p className="eyebrow">Team directory</p>
        <div className="intro-row">
          <div><h1>Meet the teams.</h1><p>Open a team to see its roster. Captains can rename their team, invite players by PID and manage the roster.</p></div>
          <Link className="button button-primary" to={`/teams/new${query({ league: leagueId })}`}>Register a team</Link>
        </div>
      </div>

      <Invitations onAnswered={message => { setAnswered(message); teams.reload() }} />

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
