import './styles/App.css'
import Header from './components/Header'
import Footer from './components/Footer'
import Home from './components/Home'
import Leagues from './components/Leagues'
import LeagueDetail from './components/LeagueDetail'
import Teams from './components/Teams'
import TeamDetail from './components/TeamDetail'
import RegisterTeam from './components/RegisterTeam'
import Schedule from './components/Schedule'
import Reports from './components/Reports'
import Resources from './components/Resources'
import SignIn from './components/SignIn'
import NotFound from './components/NotFound'
import { useState } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import type { User } from './api'
import { ActingUserContext, loadActingUser, saveActingUser } from './actingUser'

function App() {
  const [user, setUserState] = useState<User | null>(loadActingUser)

  function setUser(next: User | null) {
    setUserState(next)
    saveActingUser(next)
  }

  return (
    <ActingUserContext value={{ user, setUser }}>
      <BrowserRouter>
        <div className="app-shell">
          <Header />
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/leagues" element={<Leagues />} />
            <Route path="/leagues/:leagueId" element={<LeagueDetail />} />
            <Route path="/teams" element={<Teams />} />
            <Route path="/teams/new" element={<RegisterTeam />} />
            <Route path="/teams/:teamId" element={<TeamDetail />} />
            <Route path="/schedule" element={<Schedule />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/resources" element={<Resources />} />
            <Route path="/sign-in" element={<SignIn />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
          <Footer />
        </div>
      </BrowserRouter>
    </ActingUserContext>
  )
}

export default App
