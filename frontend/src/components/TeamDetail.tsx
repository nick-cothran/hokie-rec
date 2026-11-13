import '../styles/TeamDetail.css'
import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, formatDate, useApi, type RosterEntry, type Team } from '../api'
import { fullName, useAuth } from '../auth'

// S3: the captain renames the team. Keyed on the saved name so it reloads current values after a save.
function RenameForm({ team, onSaved }: { team: Team; onSaved: (message: string) => void }) {
  const [name, setName] = useState(team.team_name)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const unchanged = name.trim() === team.team_name

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      const saved = await api<{ team_name: string }>(`/api/teams/${team.team_id}`, {
        method: 'PATCH',
        body: JSON.stringify({ team_name: name }),
      })
      onSaved(`Team renamed to “${saved.team_name}”.`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="form-stack" onSubmit={handleSubmit}>
      <div className="form-row">
        <label className="field">Team name
          <input value={name} onChange={e => setName(e.target.value)} maxLength={60} required />
        </label>
        <button className="button button-primary" type="submit" disabled={saving || unchanged}>{saving ? 'Saving…' : 'Save name'}</button>
      </div>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
    </form>
  )
}

// The captain invites a player by their VT PID
function InviteForm({ team, onSaved }: { team: Team; onSaved: (message: string) => void }) {
  const [pid, setPid] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      const invited = await api<RosterEntry>(`/api/teams/${team.team_id}/invites`, {
        method: 'POST',
        body: JSON.stringify({ vt_pid: pid }),
      })
      setPid('')
      onSaved(`Invited ${fullName(invited)}.`)
    } catch (e) {
      setError((e as Error).message)
    }
    setSaving(false)
  }

  return (
    <form className="form-stack" onSubmit={handleSubmit}>
      <div className="form-row">
        <label className="field">Invite a player by PID
          <input value={pid} onChange={e => setPid(e.target.value)} maxLength={40} required placeholder="e.g. simvt0042" disabled={team.roster_locked} />
        </label>
        <button className="button button-primary" type="submit" disabled={saving || team.roster_locked || !pid.trim()}>{saving ? 'Inviting…' : 'Send invite'}</button>
      </div>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
    </form>
  )
}

// The captain hands captaincy to another active member
function HandOffForm({ team, onSaved, admin = false }: { team: Team; onSaved: (message: string) => void; admin?: boolean }) {
  const members = team.roster.filter(m => m.status === 'active' && m.user_id !== team.captain_id)
  const [userId, setUserId] = useState('')
  const [error, setError] = useState('')

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const member = members.find(m => m.user_id === Number(userId))
    if (!member || !window.confirm(`Make ${fullName(member)} the captain of ${team.team_name}?${admin ? '' : "\n\nYou'll stay on the roster as a regular member."}`)) return
    setError('')
    try {
      await api(`${admin ? '/api/admin' : '/api'}/teams/${team.team_id}/captain`, { method: 'PUT', body: JSON.stringify({ user_id: member.user_id }) })
      onSaved(`${fullName(member)} is now the captain.`)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  if (members.length === 0) return <p>Hand off captaincy: no other active members yet.</p>
  return (
    <form className="form-stack" onSubmit={handleSubmit}>
      <div className="form-row">
        <label className="field">Hand off captaincy
          <select value={userId} onChange={e => setUserId(e.target.value)} required>
            <option value="">Choose an active member</option>
            {members.map(m => <option key={m.user_id} value={m.user_id}>{fullName(m)}</option>)}
          </select>
        </label>
        <button className="button button-outline" type="submit" disabled={!userId}>Make captain</button>
      </div>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
    </form>
  )
}

function TeamDetail() {
  const { teamId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const { user } = useAuth()
  const id = Number(teamId)
  const valid = Number.isInteger(id) && id > 0

  const { data: team, error, loading, reload } = useApi<Team>(valid ? `/api/teams/${id}` : null)
  const eligibility = useApi<{ user_id: number; suspended: boolean }[]>(team && (user?.role === 'admin' || team.captain_id === user?.user_id) ? `/api/teams/${id}/eligibility` : null)
  const [notice, setNotice] = useState<string>(location.state?.notice ?? '')
  const [actionError, setActionError] = useState('')
  const [busy, setBusy] = useState(false)  // one roster action at a time, so a double click can't send two

  if (!valid || error === 'Team not found.') {
    return (
      <main className="content-page detail-page team-detail-page">
        <Link className="back-link" to="/teams">← Team directory</Link>
        <section className="empty-state">
          <p className="eyebrow">Team details</p>
          <h1>Team not found</h1>
          <p>There's no team with id “{teamId}”.</p>
          <Link className="button button-primary" to="/teams">Back to teams</Link>
        </section>
      </main>
    )
  }

  const captain = team?.roster.find(m => m.user_id === team.captain_id)
  const isCaptain = !!team && user?.user_id === team.captain_id
  const mine = team?.roster.find(m => m.user_id === user?.user_id)
  const activeCount = team?.roster.filter(m => m.status === 'active').length ?? 0

  function saved(message: string) {
    setNotice(message)
    setActionError('')
    reload()
  }

  // Runs a roster action after an optional confirm, then reloads the team
  async function run(path: string, method: string, success: string, confirmText?: string) {
    if (busy || (confirmText && !window.confirm(confirmText))) return
    setBusy(true)
    try {
      await api(path, { method })
      saved(success)
    } catch (e) {
      setNotice('')
      setActionError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  // S4: withdraw a pending invite
  function withdraw(member: RosterEntry) {
    if (!team) return
    run(`/api/teams/${team.team_id}/invites/${member.user_id}`, 'DELETE', `Withdrew ${fullName(member)}'s invite.`,
      `Withdraw ${fullName(member)}'s invite to ${team.team_name}?`)
  }

  function remove(member: RosterEntry) {
    if (!team) return
    run(`/api/teams/${team.team_id}/members/${member.user_id}`, 'DELETE', `Removed ${fullName(member)} from the roster.`,
      `Remove ${fullName(member)} from ${team.team_name}?\n\nThey'll stay in the roster history as removed. You can invite them again before the roster locks.`)
  }

  // Delete the team after the user confirms. Roster rows cascade; the DB blocks teams that have games.
  async function deleteTeam() {
    if (!team || !user) return
    const others = team.roster.length - 1
    const rosterNote = others > 0 ? ` Its ${others} other roster entr${others === 1 ? 'y' : 'ies'} will be removed too.` : ''
    if (!window.confirm(`Delete ${team.team_name}?${rosterNote}\n\nThis can't be undone.`)) return
    try {
      await api(`/api/teams/${team.team_id}`, { method: 'DELETE' })
      navigate(`/teams?league_id=${team.league_id}`, { state: { notice: `Deleted “${team.team_name}”.` } })
    } catch (e) {
      setNotice('')
      setActionError((e as Error).message)
    }
  }

  return (
    <main className="content-page detail-page team-detail-page">
      <Link className="back-link" to={team ? `/teams?league_id=${team.league_id}` : '/teams'}>← Team directory</Link>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {loading && !team && <p className="loading">Loading team…</p>}
      {team && (
        <div className="stack">
          <div className="page-intro">
            <p className="eyebrow"><Link className="text-link" to={`/leagues/${team.league_id}`}>{team.league_name}</Link></p>
            <h1>{team.team_name}</h1>
            <div className="form-row"><Link className="text-link" to={`/schedule?league=${team.league_id}&team=${team.team_id}`}>View schedule →</Link><Link className="text-link" to={`/reports?league=${team.league_id}`}>View standings →</Link></div>
            <ul className="meta-list">
              <li>Captain <strong>{captain ? fullName(captain) : `User #${team.captain_id}`}</strong></li>
              <li>Status <strong>{team.status}</strong></li>
              <li>Roster <strong>{activeCount} / {team.max_roster_size}</strong> (min {team.min_roster_size})</li>
              <li>{team.roster_locked ? <strong>Roster locked</strong> : <>Roster locks <strong>{formatDate(team.roster_lock_date)}</strong></>}</li>
            </ul>
          </div>

          {notice && <p className="notice notice-success" role="status">{notice}</p>}
          {user?.role === 'admin' && <section className="panel"><h2>Reassign captain</h2><HandOffForm key={team.captain_id} team={team} onSaved={saved} admin /></section>}
          {actionError && <p className="notice notice-error" role="alert">{actionError}</p>}

          {mine?.status === 'invited' && (
            <section className="panel">
              <h2>You're invited</h2>
              <p>{captain ? `${fullName(captain)} invited you` : 'You were invited'} to join {team.team_name}.{team.roster_locked ? ' The roster is locked, so you can only decline.' : ''}</p>
              <div className="form-row">
                <button className="button button-primary" type="button" disabled={busy || team.roster_locked || activeCount >= team.max_roster_size}
                  onClick={() => run(`/api/teams/${team.team_id}/invite/accept`, 'POST', `You joined ${team.team_name}.`)}>Accept</button>
                <button className="button button-outline" type="button" disabled={busy}
                  onClick={() => run(`/api/teams/${team.team_id}/invite/decline`, 'POST', 'Invite declined.')}>Decline</button>
              </div>
            </section>
          )}

          <section className="panel">
            <h2>Manage team</h2>
            {isCaptain ? (
              <div className="stack">
                <RenameForm key={team.team_name} team={team} onSaved={saved} />
                {team.roster_locked && <p className="notice notice-info">The roster locked on {formatDate(team.roster_lock_date)}. You can still rename the team, withdraw invites and hand off captaincy.</p>}
                <InviteForm team={team} onSaved={saved} />
                <HandOffForm key={team.captain_id} team={team} onSaved={saved} />
              </div>
            ) : (
              <>
                <p>Only the captain{captain ? `, ${fullName(captain)},` : ''} can rename this team or manage its roster.{user ? ` You're signed in as ${fullName(user)}.` : ''}</p>
                {!user && <Link className="button button-outline" to={`/sign-in?next=/teams/${team.team_id}`}>Sign in</Link>}
                {mine?.status === 'active' && (
                  <button className="button button-danger" type="button" disabled={busy || team.roster_locked}
                    onClick={() => run(`/api/teams/${team.team_id}/leave`, 'POST', `You left ${team.team_name}.`,
                      `Leave ${team.team_name}?\n\nThe captain can invite you back before the roster locks.`)}>
                    {team.roster_locked ? 'Roster locked' : 'Leave team'}
                  </button>
                )}
              </>
            )}
          </section>

          <section>
            <div className="section-heading"><h2>Roster</h2></div>
            {eligibility.error && <p className="notice notice-error" role="alert">Could not load private eligibility information: {eligibility.error}</p>}
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr><th>Player</th><th>Status</th>{isCaptain && <th className="num">Actions</th>}</tr>
                </thead>
                <tbody>
                  {team.roster.map(m => (
                    <tr key={m.user_id}>
                      <td>
                        {fullName(m)}
                        {m.user_id === team.captain_id && <> <span className="pill pill-captain">Captain</span></>}
                      </td>
                      <td><span className={`pill pill-${m.status}`}>{m.status === 'invited' ? 'Invite pending' : m.status}</span>{eligibility.data?.some(item => item.user_id === m.user_id && item.suspended) && <> · Suspended — not eligible to play</>}</td>
                      {isCaptain && (
                        <td className="num">
                          {m.status === 'invited' && (
                            <button className="button button-outline button-small" type="button" disabled={busy} onClick={() => withdraw(m)}>Withdraw invite</button>
                          )}
                          {m.status === 'active' && m.user_id !== team.captain_id && (
                            <button className="button button-danger button-small" type="button" disabled={busy || team.roster_locked} onClick={() => remove(m)}>Remove</button>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {isCaptain && (
            <section className="panel danger-zone">
              <h2>Delete team</h2>
              <p>Removes the team and its whole roster. Teams that already have games can't be deleted.</p>
              <button className="button button-danger" type="button" onClick={deleteTeam}>Delete this team</button>
            </section>
          )}
        </div>
      )}
    </main>
  )
}

export default TeamDetail
