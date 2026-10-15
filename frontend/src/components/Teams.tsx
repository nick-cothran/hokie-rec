import '../styles/Teams.css'
import { Link } from 'react-router-dom'

function Teams() {
  return (
    <main className="content-page teams-page">
      <div className="page-intro">
        <p className="eyebrow">Team directory</p>
        <div className="intro-row">
          <div><h1>Meet the teams.</h1><p>Find a squad and follow the season.</p></div>
        </div>
      </div>
      <section className="empty-state" aria-live="polite">
        <h2>No team information yet</h2>
        <p>Team listings will appear here when team data is connected.</p>
        <Link className="text-link" to="/leagues">Browse leagues <span aria-hidden="true">→</span></Link>
      </section>
    </main>
  )
}

export default Teams