import { createContext, useContext } from 'react'
import type { User } from './api'

// No login yet: the UI picks who it is "acting as" and sends that user_id with each write
type ActingUser = { user: User | null; setUser: (user: User | null) => void }

export const ActingUserContext = createContext<ActingUser>({ user: null, setUser: () => {} })

export function useActingUser() {
  return useContext(ActingUserContext)
}

export function fullName(person: { first_name: string; last_name: string }) {
  return `${person.first_name} ${person.last_name}`
}

const STORAGE_KEY = 'hokie-rec-acting-user'

export function loadActingUser(): User | null {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved ? JSON.parse(saved) : null
  } catch {
    return null
  }
}

export function saveActingUser(user: User | null) {
  try {
    if (user) localStorage.setItem(STORAGE_KEY, JSON.stringify(user))
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Private mode or blocked storage: the choice just won't survive a reload
  }
}
