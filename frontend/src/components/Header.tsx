import '../styles/Header.css'
import { Link, NavLink } from 'react-router-dom'
import { useActingUser } from '../actingUser'

function Header() {
  const { user } = useActingUser()

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

      <Link className="login-button" to="/sign-in">
        {user ? `Acting as ${user.first_name} ${user.last_name[0]}.` : 'Choose user'}
      </Link>
    </header>
  )
}

export default Header
