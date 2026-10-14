function Header() {
  return (
    <header className="site-header">
      <div className="brand-block">
        <div className="brand-mark">HR</div>
        <div>
          <p className="brand-name">Hokie Rec</p>
          <span className="brand-tag">Campus Leagues & Activities</span>
        </div>
      </div>

      <nav className="main-nav" aria-label="Main navigation">
        <a href="#">Leagues</a>
        <a href="#">Teams</a>
        <a href="#">Schedule</a>
        <a href="#">Resources</a>
      </nav>

      <button type="button" className="login-button">
        Sign in
      </button>
    </header>
  )
}

export default Header
