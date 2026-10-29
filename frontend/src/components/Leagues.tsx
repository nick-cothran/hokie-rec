import '../styles/Leagues.css'
import { Link, useSearchParams } from 'react-router-dom'
import { query, unique, useApi, type League } from '../api'

// S1: browse leagues by sport and term
function Leagues() {
  const [params, setParams] = useSearchParams()
  const sport = params.get('sport') ?? ''
  const term = params.get('term') ?? ''

  // Unfiltered list fills the dropdowns; the filtered request does the search
  const all = useApi<League[]>('/api/leagues')
  const results = useApi<League[]>(`/api/leagues${query({ sport, term })}`)

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  return (
    <main className="content-page leagues-page">
      <div className="page-intro">
        <p className="eyebrow">League directory</p>
        <div className="intro-row">
          <div><h1>Find your league.</h1><p>Filter by sport and term, then open a league to see its teams.</p></div>
          <Link className="button button-primary" to="/teams/new">Register a team</Link>
        </div>
      </div>

      <form className="filters" role="search" onSubmit={e => e.preventDefault()}>
        <label className="field">Sport
          <select value={sport} onChange={e => setFilter('sport', e.target.value)}>
            <option value="">All sports</option>
            {unique(all.data?.map(l => l.sport_name) ?? []).map(s => <option key={s}>{s}</option>)}
          </select>
        </label>
        <label className="field">Term
          <select value={term} onChange={e => setFilter('term', e.target.value)}>
            <option value="">All terms</option>
            {unique(all.data?.map(l => l.term) ?? []).map(t => <option key={t}>{t}</option>)}
          </select>
        </label>
        {(sport || term) && <button className="button button-outline" type="button" onClick={() => setParams({}, { replace: true })}>Clear filters</button>}
      </form>

      {results.error && <p className="notice notice-error" role="alert">{results.error}</p>}
      {results.loading && !results.data && <p className="loading">Loading leagues…</p>}
      {results.data && results.data.length === 0 && (
        <section className="empty-state"><h2>No leagues match</h2><p>Try a different sport or term.</p></section>
      )}
      {results.data && results.data.length > 0 && (
        <>
          <p className="result-count">{results.data.length} league{results.data.length === 1 ? '' : 's'}</p>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr><th>League</th><th>Sport</th><th>Category</th><th>Level</th><th>Term</th><th className="num">Teams</th></tr>
              </thead>
              <tbody>
                {results.data.map(l => (
                  <tr key={l.league_id}>
                    <td><Link to={`/leagues/${l.league_id}`}>{l.league_name}</Link></td>
                    <td>{l.sport_name}</td>
                    <td>{l.category}</td>
                    <td>{l.skill_level}</td>
                    <td>{l.term}</td>
                    <td className="num">{l.team_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </main>
  )
}

export default Leagues
