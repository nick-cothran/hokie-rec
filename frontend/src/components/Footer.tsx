import '../styles/Footer.css'
import { Link } from 'react-router-dom'

function Footer() {
  return (
    <footer className="site-footer">
      <div className="footer-brand">
        <Link to="/" className="footer-brand-link">Hokie Rec</Link>
        <p>Find your people. Play your game.</p>
      </div>

      <div className="footer-column">
        <h3>Explore</h3>
        <ul>
          <li><Link to="/leagues">Leagues</Link></li>
          <li><Link to="/teams">Teams</Link></li>
          <li><Link to="/schedule">Schedule</Link></li>
        </ul>
      </div>

      <div className="footer-column">
        <h3>Support</h3>
        <ul>
          <li><Link to="/resources">Facilities & policies</Link></li>
          <li><a href="mailto:recsports@vt.edu">Contact Rec Sports</a></li>
          <li><Link to="/resources#policies">League policies</Link></li>
        </ul>
      </div>
    </footer>
  )
}

export default Footer
