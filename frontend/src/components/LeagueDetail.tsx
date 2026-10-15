import '../styles/LeagueDetail.css'
import { Link, useParams } from 'react-router-dom'

function LeagueDetail() {
  const { leagueId } = useParams()

  return (
    <main className="content-page league-detail-page">
      <Link className="back-link" to="/leagues">← All leagues</Link>
      <section className="empty-state" aria-live="polite">
        <p className="eyebrow">League details</p>
        <h1>League information is not available yet</h1>
        <p>{leagueId ? `No league record is connected for “${leagueId}”.` : 'No league record is connected yet.'}</p>
        <Link className="button button-primary" to="/leagues">Back to leagues</Link>
      </section>
    </main>
  )
}

export default LeagueDetail