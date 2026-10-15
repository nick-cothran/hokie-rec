import '../styles/Home.css'
import { Link } from 'react-router-dom'

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