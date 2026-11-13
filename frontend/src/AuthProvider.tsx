import { useEffect, useState, type ReactNode } from 'react'
import { api, ApiError, SESSION_EXPIRED_EVENT, type Profile, type ProfileDetails, type SignUpDetails, type User } from './api'
import { AuthContext } from './auth'

export default function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    // Discard the old demo identity. Only the server can establish a session.
    try { localStorage.removeItem('hokie-rec-acting-user') } catch { /* Storage may be disabled. */ }
    function expired() {
      setUser(null)
      setError('Your session has expired. Please sign in again.')
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, expired)
    api<User>('/api/auth/me', { signal: controller.signal }).then(
      current => { if (!controller.signal.aborted) setUser(current) },
      failure => {
        if (!controller.signal.aborted && !(failure instanceof ApiError && failure.status === 401)) {
          setError((failure as Error).message)
        }
      },
    ).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => {
      controller.abort()
      window.removeEventListener(SESSION_EXPIRED_EVENT, expired)
    }
  }, [])

  async function signIn(pid: string, password: string) {
    const current = await api<User>('/api/auth/login', {
      method: 'POST', body: JSON.stringify({ vt_pid: pid.trim(), password }),
    })
    setUser(current)
    setError('')
    return current
  }

  async function signOut() {
    await api('/api/auth/logout', { method: 'POST' })
    setUser(null)
    setError('')
  }

  async function signUp(details: SignUpDetails) {
    const current = await api<User>('/api/auth/sign-up', {
      method: 'POST', body: JSON.stringify(details),
    })
    setUser(current)
    setError('')
  }

  async function updateProfile(details: ProfileDetails) {
    const profile = await api<Profile>('/api/me/profile', {
      method: 'PUT', body: JSON.stringify(details),
    })
    // Keep only the public session identity in context; contact details stay on the profile page.
    setUser(current => current?.user_id === profile.user_id
      ? { user_id: profile.user_id, first_name: profile.first_name, last_name: profile.last_name, role: profile.role }
      : current)
    setError('')
    return profile
  }

  return <AuthContext value={{ user, loading, error, signIn, signUp, signOut, updateProfile }}>{children}</AuthContext>
}
