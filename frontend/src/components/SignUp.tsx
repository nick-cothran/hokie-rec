import '../styles/SignIn.css'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { fullName, useAuth } from '../auth'
import { accountDestination, accountLink } from '../authNavigation'

function SignUp() {
  const { user, loading, error: sessionError, signUp } = useAuth()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [params] = useSearchParams()
  const navigate = useNavigate()

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const form = event.currentTarget
    const values = new FormData(form)
    const password = String(values.get('password'))
    if (password !== values.get('confirm_password')) {
      setError('Passwords do not match.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await signUp({
        vt_pid: String(values.get('vt_pid')).trim(),
        first_name: String(values.get('first_name')).trim(),
        last_name: String(values.get('last_name')).trim(),
        email: String(values.get('email')).trim(),
        phone: String(values.get('phone')).trim(),
        password,
      })
      form.reset()
      navigate(accountDestination(params.get('next')), { replace: true, state: { notice: 'Your player account is ready. Welcome to Hokie Rec!' } })
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="signin-page">
      <section className="signin-panel">
        <p className="eyebrow">Hokie Rec account</p>
        <h1>{user ? 'You’re signed in.' : 'Join the team.'}</h1>
        {loading ? <p role="status">Checking your session…</p> : user ? (
          <div className="signin-form">
            <p>Signed in as <strong>{fullName(user)}</strong>. Sign out before creating another account.</p>
            <Link className="button button-primary" to="/sign-in">Manage your account</Link>
          </div>
        ) : (
          <>
            <p>Create a player account to register teams and join the action.</p>
            <form className="signin-form" onSubmit={submit}>
              <fieldset className="signup-fields" disabled={busy}>
                <div className="signup-name-row">
                  <label className="field">First name<input name="first_name" autoComplete="given-name" maxLength={50} required /></label>
                  <label className="field">Last name<input name="last_name" autoComplete="family-name" maxLength={50} required /></label>
                </div>
                <label className="field">PID
                  <input name="vt_pid" autoComplete="username" autoCapitalize="none" spellCheck={false} pattern="[a-zA-Z0-9_\-]+" maxLength={40} aria-describedby="signup-pid-help" required />
                  <small id="signup-pid-help">Your unique sign-in name. Use letters, numbers, underscores, or hyphens.</small>
                </label>
                <label className="field">Email<input name="email" type="email" autoComplete="email" maxLength={100} required /></label>
                <label className="field">Phone number<input name="phone" type="tel" autoComplete="tel" minLength={7} maxLength={20} required /></label>
                <label className="field">Password
                  <input name="password" type="password" autoComplete="new-password" minLength={12} maxLength={128} aria-describedby="signup-password-help" required />
                  <small id="signup-password-help">Use 12–128 characters. Spaces are welcome.</small>
                </label>
                <label className="field">Confirm password<input name="confirm_password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required /></label>
                <button className="button button-primary" type="submit">{busy ? 'Creating account…' : 'Create account'}</button>
              </fieldset>
            </form>
            <p className="signin-help">Already have an account? <Link to={accountLink('/sign-in', params.get('next'))}>Sign in</Link>.</p>
          </>
        )}
        {(error || sessionError) && <p className="notice notice-error" role="alert">{error || sessionError}</p>}
        <p className="signin-help">Just looking around? <Link to="/leagues">Browse leagues</Link>.</p>
      </section>
      <aside className="signin-aside"><p className="eyebrow">Hokie Rec</p><h2>Find your people.</h2><p>Start your season with a player account. Explore leagues, register a team, and bring your friends along.</p><Link className="text-link" to="/leagues">Explore leagues <span aria-hidden="true">→</span></Link></aside>
    </main>
  )
}

export default SignUp
