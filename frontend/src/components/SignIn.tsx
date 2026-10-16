import '../styles/SignIn.css'
import { Link } from 'react-router-dom'
import { useApi, type Role, type User } from '../api'
import { fullName, useActingUser } from '../actingUser'

const ROLE_GROUPS: { role: Role; label: string }[] = [
  { role: 'player', label: 'Players' },
  { role: 'official', label: 'Officials' },
  { role: 'admin', label: 'Administrators' },
]

// Stand-in for login: pick which seeded user the app acts as
function SignIn() {
  const { user, setUser } = useActingUser()
  const users = useApi<User[]>('/api/users')

  function choose(userId: string) {
    setUser(users.data?.find(u => u.user_id === Number(userId)) ?? null)
  }

  return (
    <main className="signin-page">
      <section className="signin-panel">
        <p className="eyebrow">Hokie Rec account</p>
        <h1>Who's playing?</h1>
        <p>Accounts aren't connected yet, so choose a user to act as. Only players can register teams, and only a team's captain can manage it.</p>
        <div className="signin-form">
          <label className="field">Acting as
            <select value={user?.user_id ?? ''} onChange={e => choose(e.target.value)} disabled={!users.data}>
              <option value="">{users.loading ? 'Loading users…' : 'Choose a user'}</option>
              {ROLE_GROUPS.map(group => (
                <optgroup key={group.role} label={group.label}>
                  {users.data?.filter(u => u.role === group.role).map(u => (
                    <option key={u.user_id} value={u.user_id}>{u.last_name}, {u.first_name}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
          {users.error && <p className="notice notice-error" role="alert">{users.error}</p>}
          {user && (
            <p className="notice notice-success" role="status">
              You're acting as {fullName(user)} ({user.role}). <Link to="/teams">Go to teams</Link>
            </p>
          )}
          {user && <button className="button button-outline" type="button" onClick={() => setUser(null)}>Stop acting as {user.first_name}</button>}
        </div>
        <p className="signin-help">Just looking around? <Link to="/leagues">Browse leagues without choosing a user</Link>.</p>
      </section>
      <aside className="signin-aside"><p className="eyebrow">Hokie Rec</p><h2>Your season starts here.</h2><p>Register a team, rename it, and manage your roster's pending invites.</p><Link className="text-link" to="/leagues">Find a league <span aria-hidden="true">→</span></Link></aside>
    </main>
  )
}

export default SignIn
