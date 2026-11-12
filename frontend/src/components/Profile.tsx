import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { formatCampusDate, roleLabels, useApi, type Profile as AccountProfile, type ProfileDetails } from '../api'
import { useAuth } from '../auth'
import ChangePassword from './ChangePassword'
import '../styles/SignIn.css'
import '../styles/Profile.css'

function draftFrom(profile: ProfileDetails) {
  return { first_name: profile.first_name, last_name: profile.last_name, email: profile.email, phone: profile.phone ?? '' }
}

function ProfileForm({ profile }: { profile: AccountProfile }) {
  const { updateProfile } = useAuth()
  const [baseline, setBaseline] = useState(profile)
  const [draft, setDraft] = useState(() => draftFrom(profile))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editing, setEditing] = useState(false)
  const dirty = Object.entries(draft).some(([key, value]) => value !== draftFrom(baseline)[key as keyof typeof draft])

  function edit(field: keyof typeof draft, value: string) {
    setDraft(previous => ({ ...previous, [field]: value }))
    setError('')
    setNotice('')
  }

  function reset() {
    setDraft(draftFrom(baseline))
    setError('')
    setNotice('')
    setEditing(false)
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !dirty) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const saved = await updateProfile({
        first_name: draft.first_name.trim(), last_name: draft.last_name.trim(),
        email: draft.email.trim(), phone: draft.phone.trim() || null,
      })
      setBaseline(saved)
      setDraft(draftFrom(saved))
      setEditing(false)
      setNotice('Your profile has been saved.')
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel" aria-labelledby="profile-details-heading">
      <h2 id="profile-details-heading">Personal details</h2>
      <p>Your name appears on team rosters and the reports you submit.</p>
      {!editing && <>
        <dl className="profile-personal-details">
          <div><dt>Name</dt><dd>{baseline.first_name} {baseline.last_name}</dd></div>
          <div><dt>Email</dt><dd>{baseline.email}</dd></div>
          <div><dt>Phone number</dt><dd>{baseline.phone || 'Not provided'}</dd></div>
        </dl>
        {notice && <p className="notice notice-success" role="status">{notice}</p>}
        <button className="button button-outline" type="button" onClick={() => { setNotice(''); setEditing(true) }}>Edit details</button>
      </>}
      {editing && (
      <form className="form-stack profile-form" onSubmit={submit}>
        <fieldset className="profile-fields" disabled={busy}>
          <legend className="profile-sr-only">Edit your personal details</legend>
          <div className="profile-name-row">
            <label className="field">First name
              <input name="first_name" autoComplete="given-name" value={draft.first_name} onChange={event => edit('first_name', event.target.value)} maxLength={50} required />
            </label>
            <label className="field">Last name
              <input name="last_name" autoComplete="family-name" value={draft.last_name} onChange={event => edit('last_name', event.target.value)} maxLength={50} required />
            </label>
          </div>
          <label className="field">Email
            <input name="email" type="email" autoComplete="email" value={draft.email} onChange={event => edit('email', event.target.value)} maxLength={100} required />
          </label>
          <label className="field">Phone number <small>Optional</small>
            <input name="phone" type="tel" autoComplete="tel" value={draft.phone} onChange={event => edit('phone', event.target.value)} minLength={7} maxLength={20} aria-describedby="profile-phone-help" />
            <small id="profile-phone-help">Leave blank to remove your phone number.</small>
          </label>
          <div className="form-row">
            <button className="button button-primary" type="submit" disabled={!dirty}>{busy ? 'Saving…' : 'Save changes'}</button>
            <button className="button button-outline" type="button" onClick={reset}>Cancel</button>
          </div>
        </fieldset>
        {error && <p className="notice notice-error" role="alert">{error}</p>}
        {notice && <p className="notice notice-success" role="status">{notice}</p>}
      </form>
      )}
    </section>
  )
}

export default function Profile() {
  const { user, loading: checkingSession, error: sessionError, signOut } = useAuth()
  const response = useApi<AccountProfile>(user ? '/api/me/profile' : null)
  const profile = !response.error && user && response.data?.user_id === user.user_id ? response.data : undefined
  const [signingOut, setSigningOut] = useState(false)
  const [signOutError, setSignOutError] = useState('')

  async function logout() {
    setSigningOut(true)
    setSignOutError('')
    try { await signOut() } catch (failure) { setSignOutError((failure as Error).message) }
    finally { setSigningOut(false) }
  }

  if (checkingSession) return <main className="content-page"><p role="status">Checking your session…</p></main>
  if (!user) {
    return (
      <main className="content-page">
        <section className="empty-state">
          <h1>Your profile</h1>
          <p>Sign in to view and edit your profile.</p>
          <Link className="button button-primary" to="/sign-in?next=%2Fprofile">Sign in</Link>
        </section>
        {sessionError && <p className="notice notice-error" role="alert">{sessionError}</p>}
      </main>
    )
  }

  return (
    <main className="content-page profile-page">
      <div className="page-intro">
        <p className="eyebrow">Your account</p>
        <h1>Your profile.</h1>
        <p>Keep your name and contact information up to date.</p>
      </div>
      {response.loading && !profile && <p role="status">Loading your profile…</p>}
      {response.error && (
        <div className="stack">
          <p className="notice notice-error" role="alert">{response.error}</p>
          <div><button className="button button-outline" type="button" onClick={response.reload}>Try again</button></div>
        </div>
      )}
      {profile && (
        <div className="stack">
          <section className="panel" aria-labelledby="account-details-heading">
            <h2 id="account-details-heading">Account details</h2>
            <dl className="profile-account-details">
              <div><dt>PID</dt><dd>{profile.vt_pid}</dd></div>
              <div><dt>Role</dt><dd>{roleLabels[profile.role]}</dd></div>
              <div><dt>Joined</dt><dd>{formatCampusDate(profile.created_at)}</dd></div>
            </dl>
            <p className="profile-account-help">Your PID and account role cannot be changed here.</p>
            <div className="form-row">
              <button className="button button-outline button-small" type="button" onClick={logout} disabled={signingOut}>{signingOut ? 'Signing out…' : 'Sign out'}</button>
              {user.role === 'admin' && <Link className="text-link" to="/admin/users">Manage accounts →</Link>}
            </div>
            {signOutError && <p className="notice notice-error" role="alert">{signOutError}</p>}
          </section>
          <ProfileForm key={profile.user_id} profile={profile} />
          <section className="panel profile-password"><ChangePassword /></section>
        </div>
      )}
    </main>
  )
}
