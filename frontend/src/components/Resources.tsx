import '../styles/Resources.css'
import { Link } from 'react-router-dom'

function Resources() {
  return (
    <main className="content-page resources-page">
      <div className="page-intro">
        <p className="eyebrow">Your guide to game day</p>
        <div className="intro-row">
          <div><h1>Resources.</h1><p>Useful starting points for participating in campus recreation.</p></div>
        </div>
      </div>
      <section className="resource-section" id="policies">
        <div className="section-heading"><div><p className="eyebrow">Get started</p><h2>Player information</h2></div></div>
        <div className="resource-links">
          <Link to="/leagues"><strong>League information</strong><span>See available recreation opportunities.</span><span aria-hidden="true">↗</span></Link>
          <Link to="/teams"><strong>Team information</strong><span>Find team details when they become available.</span><span aria-hidden="true">↗</span></Link>
          <Link to="/schedule"><strong>Schedules & scores</strong><span>Check fixtures and results when published.</span><span aria-hidden="true">↗</span></Link>
        </div>
      </section>
      <section className="resource-contact">
        <div><p className="eyebrow">Need a hand?</p><h2>Talk to Rec Sports.</h2><p>Questions about participation or campus recreation?</p></div>
        <a className="button button-primary" href="mailto:recsports@vt.edu">Contact Rec Sports</a>
      </section>
    </main>
  )
}

export default Resources