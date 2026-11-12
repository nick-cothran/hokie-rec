import { useState, type FormEvent } from 'react'
import { api } from '../api'

function ChangePassword() {
  const [step, setStep] = useState<'closed' | 'verify' | 'new'>('closed')
  const [currentPassword, setCurrentPassword] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  function cancel() {
    setCurrentPassword('')
    setError('')
    setNotice('')
    setStep('closed')
  }

  async function verify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await api('/api/auth/password/verify', { method: 'POST', body: JSON.stringify({ current_password: currentPassword }) })
      setStep('new')
    } catch (failure) {
      setError((failure as Error).message)
    } finally { setBusy(false) }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const form = event.currentTarget
    const values = new FormData(form)
    const newPassword = String(values.get('new_password'))
    if (newPassword !== values.get('confirm_password')) {
      setError('New passwords do not match.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await api('/api/auth/password', {
        method: 'POST', body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      })
      form.reset()
      setCurrentPassword('')
      setStep('closed')
      setNotice('Password changed. Any other devices signed in to your account were signed out.')
    } catch (failure) {
      setError((failure as Error).message)
    } finally { setBusy(false) }
  }

  return (
    <div className="change-password" aria-labelledby="change-password-heading">
      <h2 id="change-password-heading">Change password</h2>
      {step === 'closed' && <button className="button button-outline" type="button" onClick={() => { setNotice(''); setStep('verify') }}>Change password</button>}
      {step === 'verify' && <form className="signin-form" onSubmit={verify}>
        <p>First, confirm your current password.</p>
        <fieldset className="signup-fields" disabled={busy}>
          <label className="field">Current password
            <input type="password" autoComplete="current-password" maxLength={128} value={currentPassword} onChange={event => setCurrentPassword(event.target.value)} required />
          </label>
          <button className="button button-primary" type="submit">{busy ? 'Checking…' : 'Continue'}</button>
          <button className="button button-outline" type="button" onClick={cancel}>Cancel</button>
        </fieldset>
      </form>}
      {step === 'new' && <form className="signin-form" onSubmit={submit}>
        <p>Current password confirmed. Choose a new password.</p>
        <fieldset className="signup-fields" disabled={busy}>
          <label className="field">New password
            <input name="new_password" type="password" autoComplete="new-password" minLength={12} maxLength={128} aria-describedby="new-password-help" required />
            <small id="new-password-help">Use 12–128 characters. Spaces are welcome.</small>
          </label>
          <label className="field">Confirm new password
            <input name="confirm_password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required />
          </label>
          <button className="button button-primary" type="submit">{busy ? 'Saving…' : 'Save password'}</button>
          <button className="button button-outline" type="button" onClick={cancel}>Cancel</button>
        </fieldset>
      </form>}
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {notice && <p className="notice notice-success" role="status">{notice}</p>}
    </div>
  )
}

export default ChangePassword
