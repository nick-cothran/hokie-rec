import './App.css'
import Header from './components/Header'
import Footer from './components/Footer'

function App() {
  return (
    <div className="app-shell">
      <Header />

      <main className="page-content">
        <section className="hero-panel">
          <p className="eyebrow">Welcome</p>
          <h1>Play, compete, and connect.</h1>
          <p className="subtext">
            Discover upcoming leagues, manage teams, and stay on top of game day.
          </p>
        </section>
      </main>

      <Footer />
    </div>
  )
}

export default App
