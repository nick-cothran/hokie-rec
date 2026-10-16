import '../styles/Home.css'
import { Link } from 'react-router-dom'
import { useApi, type Health } from '../api'

// Proves the UI is talking to the database (Task 4)
function ConnectionStatus() {
  const { data, error, loading } = useApi<Health>('/api/health')
  const state = loading ? '' : data ? 'is-connected' : 'is-down'

  return (
    <div className={`connection-card ${state}`} role="status">
      <span className="connection-dot" aria-hidden="true" />
      {loading && <p>Checking database connection…</p>}
      {data && (
        <p>
          <strong>Connected to {data.version.split(' on ')[0]}</strong> · database “{data.database}” · {data.leagues} leagues, {data.teams} teams
        </p>
      )}
      {error && <p><strong>Not connected.</strong> {error}</p>}
    </div>
  )
}

function Home() {
  return (
    <main className="home-page">
      <section className="home-hero">
        <div className="home-hero-copy">
          <p className="eyebrow">Virginia Tech Intramural Sports</p>
          <h1>Make your next move a team sport.</h1>
          <p>Join a league, find a team, and make game day part of your Hokie experience.</p>
          <div className="hero-actions">
            <Link className="button button-primary" to="/leagues">Explore leagues</Link>
            <Link className="text-link" to="/schedule">View the schedule <span aria-hidden="true">→</span></Link>
          </div>
        </div>
      </section>
      <ConnectionStatus />

      <section className="home-section">
        <div className="section-heading">
          <div><p className="eyebrow">Hokie Rec</p><h2>Choose where to start</h2></div>
        </div>
        <div className="home-links">
          <Link to="/leagues"><strong>Leagues</strong><span>Browse recreation opportunities</span><span aria-hidden="true">↗</span></Link>
          <Link to="/teams"><strong>Teams</strong><span>Find team information</span><span aria-hidden="true">↗</span></Link>
          <Link to="/schedule"><strong>Schedule</strong><span>Check upcoming games</span><span aria-hidden="true">↗</span></Link>
        </div>
      </section>
      <section className="home-bottom-band">
        <div><p className="eyebrow">Start playing</p><h2>New to intramurals?</h2><p>Get the basics on facilities, eligibility, and how league play works.</p></div>
        <Link className="button button-light" to="/resources">Explore resources</Link>
      </section>
    </main>
  )
}

export default Home