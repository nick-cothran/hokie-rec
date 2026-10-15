import '../styles/Header.css'
import { Link, NavLink } from 'react-router-dom'

function Header() {
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
        <NavLink to="/resources">Resources</NavLink>
      </nav>

      <Link className="login-button" to="/sign-in">Sign in</Link>
    </header>
  )
}

export default Header
