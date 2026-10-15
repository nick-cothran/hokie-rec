import '../styles/SignIn.css'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

function SignIn() {
  const [notice, setNotice] = useState('')

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setNotice('Account sign-in is not connected yet. Your credentials were not sent.')
  }

  return (
    <main className="signin-page">
      <section className="signin-panel">
        <p className="eyebrow">Hokie Rec account</p>
        <h1>Welcome back.</h1>
        <p>Sign in to manage your teams and league registration.</p>
        <form onSubmit={handleSubmit} className="signin-form">
          <label>Virginia Tech email<input type="email" name="email" autoComplete="email" placeholder="you@vt.edu" required /></label>
          <label>Password<input type="password" name="password" autoComplete="current-password" placeholder="Enter your password" required /></label>
          <button className="button button-primary" type="submit">Sign in</button>
          {notice && <p className="form-notice" role="status">{notice}</p>}
        </form>
        <p className="signin-help">Just looking around? <Link to="/leagues">Browse leagues without signing in</Link>.</p>
      </section>
      <aside className="signin-aside"><p className="eyebrow">Hokie Rec</p><h2>Your season starts here.</h2><p>Browse recreation information while account services are being connected.</p><Link className="text-link" to="/resources">View resources <span aria-hidden="true">→</span></Link></aside>
    </main>
  )
}

export default SignIn