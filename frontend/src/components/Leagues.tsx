import '../styles/Leagues.css'
import { Link } from 'react-router-dom'

function Leagues() {
  return (
    <main className="content-page leagues-page">
      <div className="page-intro">
        <p className="eyebrow">League directory</p>
        <div className="intro-row">
          <div><h1>Find your league.</h1><p>Browse recreation opportunities and get ready to play.</p></div>
        </div>
      </div>
      <section className="empty-state" aria-live="polite">
        <h2>No league information yet</h2>
        <p>League listings will appear here when league data is connected.</p>
        <Link className="text-link" to="/resources">Explore player resources <span aria-hidden="true">→</span></Link>
      </section>
    </main>
  )
}

export default Leagues