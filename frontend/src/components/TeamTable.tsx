import { Link } from 'react-router-dom'
import type { TeamSummary } from '../api'

function TeamTable({ teams, showLeague = true }: { teams: TeamSummary[]; showLeague?: boolean }) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Team</th>
            {showLeague && <th>League</th>}
            <th>Captain</th>
            <th>Status</th>
            <th className="num">Active members</th>
          </tr>
        </thead>
        <tbody>
          {teams.map(t => (
            <tr key={t.team_id}>
              <td><Link to={`/teams/${t.team_id}`}>{t.team_name}</Link></td>
              {showLeague && <td><Link to={`/leagues/${t.league_id}`}>{t.league_name}</Link></td>}
              <td>{t.captain_first_name} {t.captain_last_name}</td>
              <td><span className={`pill pill-${t.status}`}>{t.status}</span></td>
              <td className="num">{t.member_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default TeamTable
