import { createContext, useContext } from 'react'
import type { Profile, ProfileDetails, SignUpDetails, User } from './api'

type Auth = {
  user: User | null
  loading: boolean
  error: string
  signIn: (pid: string, password: string) => Promise<void>
  signUp: (details: SignUpDetails) => Promise<void>
  signOut: () => Promise<void>
  updateProfile: (details: ProfileDetails) => Promise<Profile>
}

export const AuthContext = createContext<Auth | null>(null)

export function useAuth() {
  const auth = useContext(AuthContext)
  if (!auth) throw new Error('useAuth must be used within AuthProvider')
  return auth
}

export function fullName(person: { first_name: string; last_name: string }) {
  return `${person.first_name} ${person.last_name}`
}
