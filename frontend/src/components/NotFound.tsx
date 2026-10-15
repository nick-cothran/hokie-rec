import '../styles/NotFound.css'
import { Link } from 'react-router-dom'

function NotFound() {
  return (
    <main className="not-found-page">
      <p className="eyebrow">404 · Out of bounds</p>
      <h1>That page isn’t on the schedule.</h1>
      <p>Try one of the main sections and get back in the game.</p>
      <Link className="button button-primary" to="/">Back to home</Link>
    </main>
  )
}

export default NotFound