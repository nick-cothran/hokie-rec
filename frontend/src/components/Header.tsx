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
        {(user?.role === 'official' || user?.role === 'admin') && <NavLink to="/incidents">Incidents</NavLink>}
        {user?.role === 'admin' && <NavLink to="/admin/users">Admin</NavLink>}
      </nav>

      <NavLink to={user ? '/profile' : '/sign-in'} end className={({ isActive }) => `login-button${user && isActive ? ' active' : ''}`} aria-label={user ? `${user.first_name} ${user.last_name[0]}. account` : undefined}>
        <span className="account-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="8" r="3.5" /><path d="M5.5 20a6.5 6.5 0 0 1 13 0" /></svg></span>
        <span>{loading ? 'Checking session…' : user ? `${user.first_name} ${user.last_name[0]}.` : 'Sign in'}</span>
      </NavLink>
    </header>
  )
}

export default Header
