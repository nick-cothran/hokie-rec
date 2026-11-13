import '../styles/Reports.css'
import { Link, useSearchParams } from 'react-router-dom'
import { query, unique, useApi, type League, type Participation, type Standing } from '../api'
import { paginate } from '../pagination'
import Pagination from './Pagination'
import ViewTabs from './ViewTabs'

function Reports() {
  const [params, setParams] = useSearchParams()
  const leagues = useApi<League[]>('/api/leagues')
  // Default to the first league that has teams, so standings aren't empty on first load
  const leagueId = params.get('league') ?? String(leagues.data?.find(l => l.team_count > 0)?.league_id ?? '')
  const term = params.get('term') ?? ''
  const showParticipation = params.get('view') === 'participation' || (!params.has('view') && (params.has('term') || params.has('participation_page')) && !params.has('league'))

  const standings = useApi<Standing[]>(leagueId ? `/api/reports/standings${query({ league_id: leagueId })}` : null)
  const participation = useApi<Participation[]>(`/api/reports/participation${query({ term })}`)
  const participationPage = paginate(participation.data ?? [], params.get('participation_page'))

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (key === 'term') next.delete('participation_page')
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  function setParticipationPage(page: number) {
    const next = new URLSearchParams(params)
    if (page === 1) next.delete('participation_page')
    else next.set('participation_page', String(page))
    setParams(next)
  }

  function setView(view: 'mine' | 'all') {
    const next = new URLSearchParams(params)
    next.set('view', view === 'mine' ? 'standings' : 'participation')
    setParams(next)
  }

  return (
    <main className="content-page reports-page">
      <div className="page-intro">
        <div className="intro-row">
          <div><h1>Standings & participation.</h1><p>See who's winning and how full each league is.</p></div>
        </div>
      </div>

      <ViewTabs label="Report views" personalLabel="Standings" allLabel="Participation" value={showParticipation ? 'all' : 'mine'} onChange={setView} />

      {!showParticipation && <section>
        <div className="report-heading">
          <div><h2>League standings</h2><p>Regular-season results. A forfeit counts as a loss for the team that forfeited.</p></div>
          <form className="report-filter" onSubmit={e => e.preventDefault()}>
            <label className="field">League
              <select value={leagueId} onChange={e => setParam('league', e.target.value)}>
                {leagues.data?.filter(l => l.team_count > 0).map(l => (
                  <option key={l.league_id} value={l.league_id}>{l.league_name}</option>
                ))}
              </select>
            </label>
          </form>
        </div>
        {(leagues.error || standings.error) && <p className="notice notice-error" role="alert">{leagues.error || standings.error}</p>}
        {standings.loading && !standings.data && <p className="loading">Loading standings…</p>}
        {standings.data && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="num">#</th><th>Team</th><th className="num">Played</th><th className="num">W</th>
                  <th className="num">L</th><th className="num">T</th><th className="num">Points for</th>
                  <th className="num">Points against</th><th className="num">Diff</th>
                </tr>
              </thead>
              <tbody>
                {standings.data.map((t, i) => (
                  <tr key={t.team_id}>
                    <td className="num">{i + 1}</td>
                    <td><Link to={`/teams/${t.team_id}`}>{t.team_name}</Link></td>
                    <td className="num">{t.played}</td>
                    <td className="num">{t.wins}</td>
                    <td className="num">{t.losses}</td>
                    <td className="num">{t.ties}</td>
                    <td className="num">{t.points_for}</td>
                    <td className="num">{t.points_against}</td>
                    <td className="num">{t.point_diff > 0 ? `+${t.point_diff}` : t.point_diff}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>}

      {showParticipation && <section>
        <div className="report-heading">
          <div><h2>League participation</h2><p>Teams, players and games for each league.</p></div>
          <form className="report-filter" onSubmit={e => e.preventDefault()}>
            <label className="field">Term
              <select value={term} onChange={e => setParam('term', e.target.value)}>
                <option value="">All terms</option>
                {unique(leagues.data?.map(l => l.term) ?? []).map(t => <option key={t}>{t}</option>)}
              </select>
            </label>
          </form>
        </div>
        {participation.error && <p className="notice notice-error" role="alert">{participation.error}</p>}
        {participation.loading && !participation.data && <p className="loading">Loading participation…</p>}
        {participation.data && (
          <>
            {!!participation.data.length && <p className="result-count">Showing {participationPage.start + 1}–{participationPage.end} of {participation.data.length} league{participation.data.length === 1 ? '' : 's'}</p>}
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>League</th><th>Term</th><th className="num">Teams</th><th className="num">Active players</th>
                    <th className="num">Pending invites</th><th className="num">Avg roster (max)</th>
                    <th className="num">Games played</th><th className="num">Games left</th>
                  </tr>
                </thead>
                <tbody>
                  {participationPage.items.map(l => (
                    <tr key={l.league_id}>
                      <td><Link to={`/leagues/${l.league_id}`}>{l.league_name}</Link></td>
                      <td>{l.term}</td>
                      <td className="num">{l.teams}</td>
                      <td className="num">{l.active_players}</td>
                      <td className="num">{l.pending_invites}</td>
                      <td className="num">{l.avg_roster_size ?? '–'} ({l.max_roster_size})</td>
                      <td className="num">{l.games_played}</td>
                      <td className="num">{l.games_remaining}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={participationPage.page} pageCount={participationPage.pageCount} onPageChange={setParticipationPage} />
          </>
        )}
      </section>}
    </main>
  )
}

export default Reports
