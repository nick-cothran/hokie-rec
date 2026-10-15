import '../styles/TeamDetail.css'
import { Link, useParams } from 'react-router-dom'

function TeamDetail() {
  const { teamId } = useParams()

  return (
    <main className="content-page team-detail-page">
      <Link className="back-link" to="/teams">← Team directory</Link>
      <section className="empty-state" aria-live="polite">
        <p className="eyebrow">Team details</p>
        <h1>Team information is not available yet</h1>
        <p>{teamId ? `No team record is connected for “${teamId}”.` : 'No team record is connected yet.'}</p>
        <Link className="button button-primary" to="/teams">Back to teams</Link>
      </section>
    </main>
  )
}

export default TeamDetail