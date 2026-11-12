import '../styles/Header.css'
import { Link, NavLink } from 'react-router-dom'
import { useAuth } from '../auth'

function Header() {
  const { user, loading } = useAuth()

  return (
    <header className="site-header">
      <Link className="brand-block" to="/" aria-label="Hokie Rec home">
        <div className="brand-mark">HR</div>
        <div>
          <p className="brand-name">Hokie Rec</p>
          <span className="brand-tag">Campus Leagues & Activities</span>
        </div>
      </Link>

      <nav className="main-nav" aria-label="Main navigation">
        <NavLink to="/leagues">Leagues</NavLink>
        <NavLink to="/teams">Teams</NavLink>
        <NavLink to="/schedule">Schedule</NavLink>
        <NavLink to="/reports">Reports</NavLink>
        <NavLink to="/incidents">Incidents</NavLink>
        <NavLink to="/resources">Resources</NavLink>
        {user?.role === 'admin' && <NavLink to="/admin/users">Admin</NavLink>}
      </nav>

      <Link className="login-button" to="/sign-in">
        {loading ? 'Checking session…' : user ? `${user.first_name} ${user.last_name[0]}. · Account` : 'Sign in'}
      </Link>
    </header>
  )
}

export default Header
