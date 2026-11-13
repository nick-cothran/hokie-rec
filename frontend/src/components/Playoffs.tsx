import '../styles/Playoffs.css'
import { useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, campusTime, formatGameTime as when, query, roundName, useApi, type Facility, type Game, type Standing } from '../api'
import { useAuth } from '../auth'

const record = (t?: Standing) => t ? `${t.wins}–${t.losses}${t.ties ? `–${t.ties}` : ''}` : ''

const hasResult = (g: Game) => g.forfeit_team_id !== null || g.home_score !== null

// Seeds in bracket order, so the top two seeds can only meet in the final: 4 → [1, 4, 2, 3]
function bracketOrder(size: number) {
  let order = [1]
  while (order.length < size) {
    const total = order.length * 2 + 1
    order = order.flatMap(seed => [seed, total - seed])
  }
  return order
}

function Side({ game, side, placeholder }: { game: Game; side: 'home' | 'away'; placeholder: string }) {
  const id = side === 'home' ? game.home_team_id : game.away_team_id
  const name = side === 'home' ? game.home_team_name : game.away_team_name
  const score = side === 'home' ? game.home_score : game.away_score
  const other = side === 'home' ? game.away_score : game.home_score
  const forfeited = game.forfeit_team_id !== null && game.forfeit_team_id === id
  const won = hasResult(game) && (game.forfeit_team_id !== null ? !forfeited : score !== null && other !== null && score > other)
  return (
    <div className={`bracket-team${won ? ' bracket-winner' : ''}`}>
      {id === null ? <span className="bracket-tbd">{placeholder}</span> : <Link to={`/teams/${id}`}>{name}</Link>}
      <span className="bracket-score">{forfeited ? 'Forfeit' : game.forfeit_team_id === null ? score ?? '' : ''}</span>
    </div>
  )
}

function Bracket({ games }: { games: Game[] }) {
  const bracketRef = useRef<HTMLDivElement>(null)
  const [connectors, setConnectors] = useState<{ gameId: number; path: string }[]>([])
  const rounds = [...new Set(games.map(g => g.playoff_round as number))].sort((a, b) => a - b)
  const last = rounds.at(-1) ?? 0
  useLayoutEffect(() => {
    const bracket = bracketRef.current
    if (!bracket) return

    function updateConnectors() {
      if (!bracket) return
      const bounds = bracket.getBoundingClientRect()
      const cards = new Map(Array.from(bracket.querySelectorAll<HTMLElement>('[data-bracket-game]'))
        .map(card => [Number(card.dataset.bracketGame), card.getBoundingClientRect()]))
      setConnectors(games.flatMap(game => {
        const from = cards.get(game.game_id)
        const to = game.next_game_id === null ? undefined : cards.get(game.next_game_id)
        if (!from || !to) return []
        const startX = from.right - bounds.left
        const startY = from.top + from.height / 2 - bounds.top
        const endX = to.left - bounds.left
        const endY = to.top + to.height / 2 - bounds.top
        const middleX = (startX + endX) / 2
        return [{ gameId: game.game_id, path: `M ${startX} ${startY} H ${middleX} V ${endY} H ${endX}` }]
      }))
    }

    updateConnectors()
    const observer = new ResizeObserver(updateConnectors)
    observer.observe(bracket)
    bracket.querySelectorAll<HTMLElement>('[data-bracket-game]').forEach(card => observer.observe(card))
    window.addEventListener('resize', updateConnectors)
    return () => { observer.disconnect(); window.removeEventListener('resize', updateConnectors) }
  }, [games])
  const label = (g: Game) => {
    const inRound = games.filter(x => x.playoff_round === g.playoff_round)
    const name = roundName(last - (g.playoff_round as number) + 1)
    return inRound.length > 1 ? `${name} ${inRound.indexOf(g) + 1}` : name
  }
  // An empty slot waits for the winner of the game that feeds it; the earlier feeder fills the home slot
  // (games arrive sorted by start time, then id, the same order the backend uses)
  const placeholder = (g: Game, slot: number) => {
    const feeder = games.filter(x => x.next_game_id === g.game_id)[slot]
    return feeder ? `Winner of ${label(feeder)}` : 'TBD'
  }
  const final = games.find(g => g.playoff_round === last && g.next_game_id === null)
  const champion = final && hasResult(final)
    ? (final.forfeit_team_id !== null ? final.forfeit_team_id !== final.home_team_id : (final.home_score ?? 0) > (final.away_score ?? 0))
      ? final.home_team_name : final.away_team_name
    : null

  return (
    <>
      {champion && <p className="notice notice-success" role="status">Champion: <strong>{champion}</strong></p>}
      <div className="bracket-scroll">
      <div className="bracket" ref={bracketRef} style={{ gridTemplateColumns: `repeat(${rounds.length}, minmax(220px, 1fr))`, minWidth: `${rounds.length * 220 + (rounds.length - 1) * 48}px` }}>
        <svg className="bracket-connectors" aria-hidden="true">
          {connectors.map(connector => <path key={connector.gameId} d={connector.path} />)}
        </svg>
        {rounds.map(r => (
          <div className="bracket-round" key={r}>
            <h3>{roundName(last - r + 1)}</h3>
            <div className="bracket-games">
              {games.filter(g => g.playoff_round === r).map(g => (
                <article className="bracket-game" key={g.game_id} data-bracket-game={g.game_id} aria-label={label(g)}>
                  <Side game={g} side="home" placeholder={placeholder(g, 0)} />
                  <Side game={g} side="away" placeholder={placeholder(g, 1)} />
                  <p className="bracket-meta">{when(g.start_time)} · {g.facility_name}</p>
                </article>
              ))}
            </div>
          </div>
        ))}
      </div>
      </div>
    </>
  )
}

function GenerateBracket({ leagueId, onDone }: { leagueId: number; onDone: (message: string) => void }) {
  const standings = useApi<Standing[]>(`/api/reports/standings${query({ league_id: leagueId })}`)
  const facilities = useApi<Facility[]>('/api/admin/facilities')
  const active = standings.data?.filter(t => t.team_status === 'active') ?? []
  const sizes = [2, 4, 8].filter(n => n <= active.length)
  const [size, setSize] = useState(4)
  const [facility, setFacility] = useState('')
  const [start, setStart] = useState('')
  const [gap, setGap] = useState('7')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const teamCount = sizes.includes(size) ? size : sizes.at(-1) ?? 0
  const order = bracketOrder(teamCount)
  const seeds = active.slice(0, teamCount)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const startDate = campusTime(start)
    if (!Number.isFinite(startDate.getTime())) { setError('Choose a start time.'); return }
    setBusy(true)
    setError('')
    try {
      await api(`/api/admin/leagues/${leagueId}/playoffs`, { method: 'POST', body: JSON.stringify({
        team_count: teamCount, facility_id: Number(facility), start_time: startDate.toISOString(), days_between_rounds: Number(gap),
      }) })
      onDone(`Playoff bracket created for the top ${teamCount} teams.`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (standings.error || facilities.error) return <p className="notice notice-error" role="alert">{standings.error || facilities.error}</p>
  if (!standings.data) return <p className="loading">Loading standings…</p>
  if (sizes.length === 0) return <p className="notice notice-info">A bracket needs at least two active teams.</p>

  return (
    <div className="generate-bracket">
      <form className="form-stack" onSubmit={submit}>
        <label className="field">Teams in the bracket
          <select value={teamCount} onChange={e => setSize(Number(e.target.value))} disabled={busy}>
            {sizes.map(n => <option key={n} value={n}>Top {n}</option>)}
          </select>
        </label>
        <label className="field">Facility
          <select value={facility} onChange={e => setFacility(e.target.value)} required disabled={busy || facilities.loading}>
            <option value="">Choose a facility</option>
            {facilities.data?.map(f => <option key={f.facility_id} value={f.facility_id}>{f.facility_name} — {f.location}</option>)}
          </select>
        </label>
        <label className="field">First round starts
          <input type="datetime-local" value={start} onChange={e => setStart(e.target.value)} required disabled={busy} />
          <small>First-round games run back to back from this time, in Blacksburg (Eastern) time.</small>
        </label>
        <label className="field">Days between rounds
          <input type="number" min={1} max={14} step={1} value={gap} onChange={e => setGap(e.target.value)} required disabled={busy} />
        </label>
        {error && <p className="notice notice-error" role="alert">{error}</p>}
        <div className="form-row">
          <button className="button button-primary" type="submit" disabled={busy || !facility || !start}>
            {busy ? 'Generating…' : 'Generate bracket'}
          </button>
        </div>
      </form>
      <div>
        <h3>First-round matchups</h3>
        <p className="result-count">Seeded by regular-season standings (wins, then point difference).</p>
        <ol className="matchups">
          {Array.from({ length: teamCount / 2 }, (_, i) => {
            const [a, b] = [order[2 * i], order[2 * i + 1]]
            const team = (seed: number) => <><strong>#{seed} {seeds[seed - 1]?.team_name}</strong> ({record(seeds[seed - 1])})</>
            return <li key={i}>{team(a)} vs {team(b)}</li>
          })}
        </ol>
      </div>
    </div>
  )
}

function Playoffs({ leagueId }: { leagueId: number }) {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const games = useApi<Game[]>(`/api/games${query({ league_id: leagueId })}`)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [removing, setRemoving] = useState(false)
  const playoff = games.data?.filter(g => g.playoff_round !== null) ?? []
  const started = playoff.some(hasResult)

  async function remove() {
    if (!window.confirm('Remove this playoff bracket? Its games and officiating assignments will be deleted.')) return
    setRemoving(true)
    setError('')
    try {
      await api(`/api/admin/leagues/${leagueId}/playoffs`, { method: 'DELETE' })
      setNotice('Playoff bracket removed.')
      games.reload()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRemoving(false)
    }
  }

  return (
    <section className="playoffs" aria-labelledby="playoffs-heading">
      <div className="section-heading"><h2 id="playoffs-heading">Playoffs</h2></div>
      {games.data && playoff.length > 0 && <p className="playoffs-intro">Winners advance to the next round. The winner of the final is the champion.</p>}
      {notice && <p className="notice notice-success" role="status">{notice}</p>}
      {(games.error || error) && <p className="notice notice-error" role="alert">{games.error || error}</p>}
      {games.loading && !games.data && <p className="loading">Loading playoffs…</p>}
      {games.data && playoff.length > 0 && <Bracket games={playoff} />}
      {games.data && playoff.length === 0 && !isAdmin && (
        <div className="empty-state"><h2>No playoff bracket yet</h2><p>The bracket is posted once the regular season ends.</p></div>
      )}
      {games.data && isAdmin && (
        <div className="panel">
          {playoff.length === 0 ? (
            <>
              <h2>Generate the playoff bracket</h2>
              <GenerateBracket leagueId={leagueId} onDone={message => { setNotice(message); games.reload() }} />
            </>
          ) : (
            <>
              <h2>Manage the bracket</h2>
              <p>
                {started
                  ? 'Results have been entered, so the bracket is locked. Winners move into the next round as officials enter results.'
                  : 'Assign officials to playoff games from the Schedule page. Winners move into the next round as officials enter results.'}
              </p>
              {!started && (
                <button className="button button-danger" type="button" onClick={remove} disabled={removing}>
                  {removing ? 'Removing…' : 'Remove bracket'}
                </button>
              )}
            </>
          )}
        </div>
      )}
    </section>
  )
}

export default Playoffs
