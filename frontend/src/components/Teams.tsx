import '../styles/Teams.css'
import { useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { api, formatDate, query, useApi, type Invite, type League, type MyTeam, type TeamSummary } from '../api'
import { useAuth } from '../auth'
import TeamTable from './TeamTable'
import Pagination from './Pagination'
import { paginate } from '../pagination'
import ViewTabs from './ViewTabs'

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

  if (!invites.data?.length && !error && !invites.error) return null
  return (
    <section className="panel invitations" aria-labelledby="invitations-heading">
      <h2 id="invitations-heading">Your invitations</h2>
      {(error || invites.error) && <p className="notice notice-error" role="alert">{error || invites.error}</p>}
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

function YourTeams() {
  const teams = useApi<MyTeam[]>('/api/me/teams')
  return (
    <section className="panel your-teams" aria-labelledby="your-teams-heading">
      <h2 id="your-teams-heading">Your teams</h2>
      {teams.loading && <p role="status">Loading your teams…</p>}
      {teams.error && <p className="notice notice-error" role="alert">{teams.error}</p>}
      {!teams.loading && !teams.error && teams.data?.length === 0 && <p>You aren't on a team yet. Browse the directory or register a team to get started.</p>}
      {!teams.loading && !teams.error && !!teams.data?.length && (
        <ul className="invite-list">
          {teams.data.map(team => <li key={team.team_id}>
            <div>
              <Link className="text-link" to={`/teams/${team.team_id}`}><strong>{team.team_name}</strong></Link>{' '}
              {team.is_captain && <span className="pill pill-captain">Captain</span>}
              <span className="invite-meta">{team.league_name} · {team.member_count} active {team.member_count === 1 ? 'player' : 'players'}</span>
            </div>
            <Link className="button button-outline button-small" to={`/teams/${team.team_id}`}>View team</Link>
          </li>)}
        </ul>
      )}
    </section>
  )
}

function Teams() {
  const { user, loading } = useAuth()
  const canRegister = !loading && (!user || user.role === 'player')
  const [params, setParams] = useSearchParams()
  const routeNotice: string | undefined = useLocation().state?.notice
  const [answered, setAnswered] = useState('')
  const [membershipVersion, setMembershipVersion] = useState(0)
  const notice = answered || routeNotice
  const leagueId = params.get('league_id') ?? ''
  const hasPersonalTeams = user?.role === 'player'
  const selectedView = params.get('view')
  const showPersonal = hasPersonalTeams && (selectedView === 'mine' || (selectedView !== 'all' && !params.has('league_id') && !params.has('page')))

  const leagues = useApi<League[]>('/api/leagues')
  const teams = useApi<TeamSummary[]>(`/api/teams${query({ league_id: leagueId })}`)
  const teamPage = paginate(teams.data ?? [], params.get('page'))

  function setPage(page: number) {
    const next = new URLSearchParams(params)
    if (page === 1) next.delete('page')
    else next.set('page', String(page))
    setParams(next)
  }

  function setView(view: 'mine' | 'all') {
    const next = new URLSearchParams(params)
    next.set('view', view)
    setParams(next)
  }

  return (
    <main className="content-page teams-page">
      <div className="page-intro">
        <div className="intro-row">
          <div><h1>Meet the teams.</h1><p>Open a team to see its roster. Captains can rename their team, invite players by PID and manage the roster.</p></div>
          {canRegister && <Link className="button button-primary" to={`/teams/new${query({ league: leagueId })}`}>Register a team</Link>}
        </div>
      </div>

      {hasPersonalTeams && <>
        <Invitations key={user.user_id} onAnswered={message => { setAnswered(message); setMembershipVersion(version => version + 1); teams.reload() }} />
        <ViewTabs label="Team views" personalLabel="Your teams" allLabel="All teams" value={showPersonal ? 'mine' : 'all'} onChange={setView} />
      </>}
      {notice && <p className="notice notice-success" role="status">{notice}</p>}
      {showPersonal && user && <YourTeams key={`${user.user_id}-${membershipVersion}`} />}

      {!showPersonal && <>
      <h2>All teams</h2>

      <form className="filters" role="search" onSubmit={e => e.preventDefault()}>
        <label className="field">League
          <select value={leagueId} onChange={e => setParams({ ...(e.target.value ? { league_id: e.target.value } : {}), ...(hasPersonalTeams ? { view: 'all' } : {}) }, { replace: true })}>
            <option value="">All leagues</option>
            {leagues.data?.map(l => <option key={l.league_id} value={l.league_id}>{l.league_name}</option>)}
          </select>
        </label>
      </form>

      {teams.error && <p className="notice notice-error" role="alert">{teams.error}</p>}
      {teams.loading && !teams.data && <p className="loading">Loading teams…</p>}
      {teams.data && teams.data.length === 0 && (
        <section className="empty-state">
          <h2>No teams in this league yet</h2>
          {canRegister && <Link className="text-link" to={`/teams/new${query({ league: leagueId })}`}>Register the first one <span aria-hidden="true">→</span></Link>}
        </section>
      )}
      {teams.data && teams.data.length > 0 && (
        <>
          <p className="result-count">Showing {teamPage.start + 1}–{teamPage.end} of {teams.data.length} team{teams.data.length === 1 ? '' : 's'}</p>
          <TeamTable teams={teamPage.items} />
          <Pagination page={teamPage.page} pageCount={teamPage.pageCount} onPageChange={setPage} />
        </>
      )}
      </>}
    </main>
  )
}

export default Teams
