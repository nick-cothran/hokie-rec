import { useState, type FormEvent } from 'react'
import { api } from '../api'

// Signed-in users change their password; the server signs out their other browsers
function ChangePassword() {
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const form = event.currentTarget
    const values = new FormData(form)
    const newPassword = String(values.get('new_password'))
    setNotice('')
    if (newPassword !== values.get('confirm_password')) {
      setError('New passwords do not match.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await api('/api/auth/password', {
        method: 'POST',
        body: JSON.stringify({ current_password: String(values.get('current_password')), new_password: newPassword }),
      })
      form.reset()
      setNotice('Password changed. Any other devices signed in to your account were signed out.')
    } catch (failure) {
      setError((failure as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="signin-form change-password" onSubmit={submit} aria-labelledby="change-password-heading">
      <h2 id="change-password-heading">Change password</h2>
      <fieldset className="signup-fields" disabled={busy}>
        <label className="field">Current password
          <input name="current_password" type="password" autoComplete="current-password" maxLength={128} required />
        </label>
        <label className="field">New password
          <input name="new_password" type="password" autoComplete="new-password" minLength={12} maxLength={128} aria-describedby="new-password-help" required />
          <small id="new-password-help">Use 12–128 characters. Spaces are welcome.</small>
        </label>
        <label className="field">Confirm new password
          <input name="confirm_password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required />
        </label>
        <button className="button button-outline" type="submit">{busy ? 'Saving…' : 'Change password'}</button>
      </fieldset>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {notice && <p className="notice notice-success" role="status">{notice}</p>}
    </form>
  )
}

export default ChangePassword
