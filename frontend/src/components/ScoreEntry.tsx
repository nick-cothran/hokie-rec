import '../styles/ScoreEntry.css'
import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, formatGameTime, useApi, type ScoreReport, type ScoreSheet } from '../api'
import { fullName, useAuth } from '../auth'

type Game = ScoreSheet['game']

function describe(report: ScoreReport, game: Game) {
  if (report.forfeit_team_id !== null) {
    const team = report.forfeit_team_id === game.home_team_id ? game.home_team_name : game.away_team_name
    return `Forfeit by ${team}`
  }
  return `${game.home_team_name} ${report.home_score} – ${report.away_score} ${game.away_team_name}`
}

// The assigned official enters the final score or a forfeit. A later report is a correction.
function ResultForm({ game, correcting, onSaved }: { game: Game; correcting: boolean; onSaved: (message: string) => void }) {
  const [mode, setMode] = useState<'score' | 'forfeit'>('score')
  const [home, setHome] = useState('')
  const [away, setAway] = useState('')
  const [forfeitTeam, setForfeitTeam] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const body = mode === 'score'
      ? { home_score: Number(home), away_score: Number(away) }
      : { forfeit_team_id: Number(forfeitTeam) }
    if (correcting && !window.confirm('This game already has a result. Submit a correction? Earlier reports stay in the history.')) return
    setBusy(true)
    setError('')
    try {
      await api(`/api/games/${game.game_id}/score-reports`, { method: 'POST', body: JSON.stringify(body) })
      setHome('')
      setAway('')
      setForfeitTeam('')
      onSaved(correcting ? 'Correction submitted. It is now the official result.' : 'Result submitted. Standings now include this game.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="form-stack" onSubmit={submit}>
      <fieldset className="result-mode" disabled={busy}>
        <legend>Result type</legend>
        <label><input type="radio" name="mode" checked={mode === 'score'} onChange={() => setMode('score')} /> Final score</label>
        <label><input type="radio" name="mode" checked={mode === 'forfeit'} onChange={() => setMode('forfeit')} /> Forfeit</label>
      </fieldset>
      {mode === 'score' ? (
        <div className="score-inputs">
          <label className="field">{game.home_team_name} <small>Home</small>
            <input type="number" inputMode="numeric" min={0} max={999} step={1} value={home} onChange={e => setHome(e.target.value)} required disabled={busy} />
          </label>
          <label className="field">{game.away_team_name} <small>Away</small>
            <input type="number" inputMode="numeric" min={0} max={999} step={1} value={away} onChange={e => setAway(e.target.value)} required disabled={busy} />
          </label>
        </div>
      ) : (
        <label className="field">Forfeiting team
          <select value={forfeitTeam} onChange={e => setForfeitTeam(e.target.value)} required disabled={busy}>
            <option value="">Choose the team that forfeited</option>
            <option value={game.home_team_id ?? ''}>{game.home_team_name}</option>
            <option value={game.away_team_id ?? ''}>{game.away_team_name}</option>
          </select>
          <small>A forfeit counts as a loss for that team.</small>
        </label>
      )}
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      <div className="form-row">
        <button className="button button-primary" type="submit" disabled={busy}>
          {busy ? 'Submitting…' : correcting ? 'Submit correction' : 'Submit result'}
        </button>
      </div>
    </form>
  )
}

function ScoreEntry() {
  const { gameId } = useParams()
  const { user, loading: checkingSession } = useAuth()
  const id = Number(gameId)
  const valid = Number.isInteger(id) && id > 0
  const sheet = useApi<ScoreSheet>(valid && user ? `/api/games/${id}/score-reports` : null)
  const [notice, setNotice] = useState('')

  if (!valid) {
    return <main className="content-page"><section className="empty-state"><h1>Game not found</h1><Link className="button button-primary" to="/schedule">Back to schedule</Link></section></main>
  }
  if (checkingSession) return <main className="content-page"><p className="loading">Checking your session…</p></main>
  if (!user) {
    return (
      <main className="content-page">
        <section className="empty-state">
          <p className="eyebrow">Game result</p>
          <h1>Sign in to enter results</h1>
          <p>Only the game's assigned officials and administrators can see score reports.</p>
          <Link className="button button-primary" to={`/sign-in?next=${encodeURIComponent(`/games/${id}/score`)}`}>Sign in</Link>
        </section>
      </main>
    )
  }

  const game = sheet.data?.game
  const current = sheet.data?.reports.find(r => r.is_current)

  return (
    <main className="content-page detail-page score-entry-page">
      <Link className="back-link" to={game ? `/schedule?league=${game.league_id}` : '/schedule'}>← Schedule</Link>
      {sheet.error && (
        <section className="empty-state" role="alert">
          <h1>{sheet.error === 'Game not found.' ? 'Game not found' : 'Result unavailable'}</h1>
          <p>{sheet.error}</p>
        </section>
      )}
      {sheet.loading && !sheet.data && <p className="loading">Loading game…</p>}
      {game && sheet.data && (
        <div className="stack">
          <div className="page-intro">
            <p className="eyebrow"><Link className="text-link" to={`/leagues/${game.league_id}`}>{game.league_name}</Link></p>
            <h1>{game.home_team_name ?? 'TBD'} vs {game.away_team_name ?? 'TBD'}</h1>
            <ul className="meta-list">
              <li>When <strong>{formatGameTime(game.start_time)}</strong></li>
              <li>Where <strong>{game.facility_name}</strong></li>
              <li>Status <strong>{game.status}</strong></li>
            </ul>
          </div>

          {notice && <p className="notice notice-success" role="status">{notice}</p>}

          <section className="panel" aria-labelledby="current-result-heading">
            <h2 id="current-result-heading">Official result</h2>
            <p className="current-result">{current ? describe(current, game) : 'No result submitted yet.'}</p>
          </section>

          <section className="panel" aria-labelledby="enter-result-heading">
            <h2 id="enter-result-heading">{current ? 'Correct the result' : 'Enter the result'}</h2>
            {game.playoff_round !== null && sheet.data.can_submit && (
              <p className="result-count">Playoff game: enter the score after any tiebreaker. {game.next_game_id !== null && 'The winner moves on to the next round.'}</p>
            )}
            {sheet.data.can_submit
              ? <ResultForm game={game} correcting={!!current} onSaved={message => { setNotice(message); sheet.reload() }} />
              : <p className="notice notice-info">{sheet.data.blocked_reason}</p>}
          </section>

          {sheet.data.reports.length > 0 && (
            <section aria-labelledby="history-heading">
              <div className="section-heading"><h2 id="history-heading">Report history</h2></div>
              <div className="table-wrap">
                <table className="data-table">
                  <thead><tr><th>Submitted</th><th>By</th><th>Result</th><th></th></tr></thead>
                  <tbody>
                    {sheet.data.reports.map(r => (
                      <tr key={r.report_id}>
                        <td>{formatGameTime(r.submitted_at)}</td>
                        <td>{fullName(r)}</td>
                        <td>{describe(r, game)}</td>
                        <td>{r.is_current ? <span className="pill pill-active">Current</span> : <span className="pill">Superseded</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      )}
    </main>
  )
}

export default ScoreEntry
