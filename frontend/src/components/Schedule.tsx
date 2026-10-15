import '../styles/Schedule.css'

function Schedule() {
  return (
    <main className="content-page schedule-page">
      <div className="page-intro">
        <p className="eyebrow">Game day</p>
        <div className="intro-row">
          <div><h1>Schedules & scores.</h1><p>Know where to be and who you’re playing.</p></div>
        </div>
      </div>
      <section className="empty-state" aria-live="polite">
        <h2>No games scheduled</h2>
        <p>Fixtures and scores will appear here when schedule data is connected.</p>
      </section>
    </main>
  )
}

export default Schedule