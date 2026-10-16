import '../styles/TeamDetail.css'
import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, useApi, type RosterEntry, type Team } from '../api'
import { fullName, useActingUser } from '../actingUser'

// S3: the captain renames the team. Keyed on the saved name so it reloads current values after a save.
function RenameForm({ team, onSaved }: { team: Team; onSaved: (message: string) => void }) {
  const { user } = useActingUser()
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
        body: JSON.stringify({ team_name: name, user_id: user?.user_id }),
      })
      onSaved(`Team renamed to “${saved.team_name}”.`)
    } catch (e) {
      setError((e as Error).message)
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

function TeamDetail() {
  const { teamId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const { user, setUser } = useActingUser()
  const id = Number(teamId)
  const valid = Number.isInteger(id) && id > 0

  const { data: team, error, loading, reload } = useApi<Team>(valid ? `/api/teams/${id}` : null)
  const [notice, setNotice] = useState<string>(location.state?.notice ?? '')
  const [actionError, setActionError] = useState('')

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

  function saved(message: string) {
    setNotice(message)
    setActionError('')
    reload()
  }

  // S4: withdraw a pending invite, after the user confirms
  async function withdraw(member: RosterEntry) {
    if (!team || !user) return
    if (!window.confirm(`Withdraw ${fullName(member)}'s invite to ${team.team_name}?\n\nThis removes the pending invite. It can't be undone.`)) return
    try {
      await api(`/api/teams/${team.team_id}/invites/${member.user_id}?user_id=${user.user_id}`, { method: 'DELETE' })
      saved(`Withdrew ${fullName(member)}'s invite.`)
    } catch (e) {
      setNotice('')
      setActionError((e as Error).message)
    }
  }

  // Delete the team after the user confirms. Roster rows cascade; the DB blocks teams that have games.
  async function deleteTeam() {
    if (!team || !user) return
    const others = team.roster.length - 1
    const rosterNote = others > 0 ? ` Its ${others} other roster entr${others === 1 ? 'y' : 'ies'} will be removed too.` : ''
    if (!window.confirm(`Delete ${team.team_name}?${rosterNote}\n\nThis can't be undone.`)) return
    try {
      await api(`/api/teams/${team.team_id}?user_id=${user.user_id}`, { method: 'DELETE' })
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
            <ul className="meta-list">
              <li>Captain <strong>{captain ? fullName(captain) : `User #${team.captain_id}`}</strong></li>
              <li>Status <strong>{team.status}</strong></li>
              <li>Active members <strong>{team.roster.filter(m => m.status === 'active').length}</strong></li>
            </ul>
          </div>

          {notice && <p className="notice notice-success" role="status">{notice}</p>}
          {actionError && <p className="notice notice-error" role="alert">{actionError}</p>}

          <section className="panel">
            <h2>Manage team</h2>
            {isCaptain ? (
              <RenameForm key={team.team_name} team={team} onSaved={saved} />
            ) : (
              <>
                <p>Only the captain{captain ? `, ${fullName(captain)},` : ''} can rename this team or withdraw invites.{user ? ` You're acting as ${fullName(user)}.` : ''}</p>
                {captain && (
                  <button className="button button-outline" type="button" onClick={() => setUser({ ...captain, role: 'player' })}>
                    Act as {fullName(captain)}
                  </button>
                )}
              </>
            )}
          </section>

          <section>
            <div className="section-heading"><h2>Roster</h2></div>
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
                      <td><span className={`pill pill-${m.status}`}>{m.status === 'invited' ? 'Invite pending' : m.status}</span></td>
                      {isCaptain && (
                        <td className="num">
                          {m.status === 'invited' && (
                            <button className="button button-outline button-small" type="button" onClick={() => withdraw(m)}>Withdraw invite</button>
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
