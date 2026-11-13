import '../styles/Footer.css'
import { Link } from 'react-router-dom'

function Footer() {
  return (
    <footer className="site-footer">
      <div className="footer-brand">
        <Link to="/" className="footer-brand-link">Hokie Rec</Link>
        <p>Intramural sports, all in one place.</p>
      </div>
      <nav className="footer-nav" aria-label="Footer navigation">
        <Link to="/leagues">Leagues</Link>
        <Link to="/teams">Teams</Link>
        <Link to="/schedule">Schedule</Link>
        <Link to="/reports">Reports</Link>
      </nav>
      <a className="footer-contact" href="mailto:recsports@vt.edu">Contact Rec Sports</a>
    </footer>
  )
}

export default Footer
