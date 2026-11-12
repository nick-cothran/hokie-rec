import '../styles/AdminUsers.css'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, formatCampusDate, roleLabels, useApi, type AdminUser, type Role, type User } from '../api'
import { fullName, useAuth } from '../auth'

const ROLES = Object.entries(roleLabels).map(([value, label]) => ({ value, label }))
const roleLabel = (role: Role) => roleLabels[role] ?? role

// An administrator creates a player, official or administrator with an initial password
function CreateAccount({ onCreated }: { onCreated: (message: string) => void }) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const form = event.currentTarget
    const values = new FormData(form)
    const text = (name: string) => String(values.get(name)).trim()
    const password = String(values.get('password'))
    if (password !== values.get('confirm_password')) {
      setError('Passwords do not match.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const created = await api<User>('/api/admin/users', {
        method: 'POST',
        body: JSON.stringify({
          vt_pid: text('vt_pid'), first_name: text('first_name'), last_name: text('last_name'),
          email: text('email'), phone: text('phone'), role: values.get('role'), password,
        }),
      })
      form.reset()
      onCreated(`Created ${roleLabel(created.role as Role).toLowerCase()} account for ${fullName(created)}. They can sign in with PID “${text('vt_pid').toLowerCase()}” and the initial password, then change it from their account page.`)
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel" aria-labelledby="create-account-heading">
      <h2 id="create-account-heading">Create an account</h2>
      <p>Use this for officials and administrators, who can't sign themselves up. Share the initial password with them privately.</p>
      <form onSubmit={submit}>
        <fieldset className="admin-form-grid" disabled={busy}>
          <label className="field">First name<input name="first_name" autoComplete="off" maxLength={50} required /></label>
          <label className="field">Last name<input name="last_name" autoComplete="off" maxLength={50} required /></label>
          <label className="field">PID
            <input name="vt_pid" autoComplete="off" autoCapitalize="none" spellCheck={false} pattern="[a-zA-Z0-9_\-]+" maxLength={40} required />
          </label>
          <label className="field">Role
            <select name="role" defaultValue="official" required>
              {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </label>
          <label className="field">Email<input name="email" type="email" autoComplete="off" maxLength={100} required /></label>
          <label className="field">Phone number<input name="phone" type="tel" autoComplete="off" minLength={7} maxLength={20} required /></label>
          <label className="field">Initial password
            <input name="password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required />
            <small>12–128 characters.</small>
          </label>
          <label className="field">Confirm initial password
            <input name="confirm_password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required />
          </label>
          <div className="admin-form-actions">
            <button className="button button-primary" type="submit">{busy ? 'Creating…' : 'Create account'}</button>
          </div>
        </fieldset>
        {error && <p className="notice notice-error" role="alert">{error}</p>}
      </form>
    </section>
  )
}

function AdminUsers() {
  const { user, loading } = useAuth()
  const isAdmin = user?.role === 'admin'
  const users = useApi<AdminUser[]>(isAdmin ? '/api/admin/users' : null)
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [role, setRole] = useState('')

  if (loading) return <main className="content-page"><p className="loading">Checking your session…</p></main>
  if (!isAdmin) {
    return (
      <main className="content-page">
        <section className="empty-state">
          <p className="eyebrow">Administration</p>
          <h1>Administrators only</h1>
          <p>{user ? `You're signed in as ${fullName(user)}, who is not an administrator.` : 'Sign in with an administrator account to manage accounts.'}</p>
          {!user && <Link className="button button-primary" to="/sign-in?next=%2Fadmin%2Fusers">Sign in</Link>}
        </section>
      </main>
    )
  }

  const term = search.trim().toLowerCase()
  const shown = users.data?.filter(u => (!role || u.role === role) && (!term ||
    `${u.first_name} ${u.last_name} ${u.vt_pid} ${u.email}`.toLowerCase().includes(term)))

  return (
    <main className="content-page admin-users-page">
      <div className="page-intro">
        <p className="eyebrow">Administration</p>
        <h1>Accounts.</h1>
        <p>Create accounts for officials and administrators, and look up anyone who uses Hokie Rec.</p>
      </div>

      <div className="stack">
        {notice && <p className="notice notice-success" role="status">{notice}</p>}
        <CreateAccount onCreated={message => { setNotice(message); users.reload() }} />

        <section aria-labelledby="all-accounts-heading">
          <div className="section-heading"><h2 id="all-accounts-heading">All accounts</h2></div>
          <form className="filters" role="search" onSubmit={e => e.preventDefault()}>
            <label className="field">Search
              <input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Name, PID or email" />
            </label>
            <label className="field">Role
              <select value={role} onChange={e => setRole(e.target.value)}>
                <option value="">All roles</option>
                {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}s</option>)}
              </select>
            </label>
          </form>
          {users.error && <p className="notice notice-error" role="alert">{users.error}</p>}
          {users.loading && !users.data && <p className="loading">Loading accounts…</p>}
          {shown && (
            <>
              <p className="result-count">{shown.length} account{shown.length === 1 ? '' : 's'}</p>
              <div className="table-wrap">
                <table className="data-table">
                  <thead><tr><th>Name</th><th>PID</th><th>Email</th><th>Role</th><th>Status</th><th>Joined</th></tr></thead>
                  <tbody>
                    {shown.map(u => (
                      <tr key={u.user_id}>
                        <td>{fullName(u)}</td>
                        <td>{u.vt_pid}</td>
                        <td>{u.email}</td>
                        <td><span className={`pill pill-role-${u.role}`}>{roleLabel(u.role)}</span></td>
                        <td>{u.is_active ? 'Active' : 'Inactive'}</td>
                        <td>{formatCampusDate(u.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  )
}

export default AdminUsers
