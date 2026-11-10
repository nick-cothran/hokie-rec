import { useCallback, useEffect, useState } from 'react'

export const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type Role = 'player' | 'official' | 'admin'

export type User = { user_id: number; first_name: string; last_name: string; role: Role }

export type SignUpDetails = {
  vt_pid: string
  first_name: string
  last_name: string
  email: string
  phone: string
  password: string
}

export type Health = { status: string; version: string; database: string; leagues: number; teams: number }

export type League = {
  league_id: number
  league_name: string
  sport_name: string
  category: string
  skill_level: string
  term: string
  team_count: number
}

export type TeamSummary = {
  team_id: number
  team_name: string
  status: string
  league_id: number
  league_name: string
  sport_name: string
  term: string
  captain_first_name: string
  captain_last_name: string
  member_count: number
}

export type RosterEntry = { user_id: number; first_name: string; last_name: string; status: string }

export type Team = {
  team_id: number
  team_name: string
  status: string
  captain_id: number
  league_id: number
  league_name: string
  min_roster_size: number
  max_roster_size: number
  roster_lock_date: string
  roster_locked: boolean
  roster: RosterEntry[]
}

// One of the signed-in player's pending invites (GET /api/me/invites)
export type Invite = {
  team_id: number
  team_name: string
  league_id: number
  league_name: string
  captain_first_name: string
  captain_last_name: string
  roster_lock_date: string
  roster_locked: boolean
  active_count: number
  max_roster_size: number
}

// "2027-01-24" → "Jan 24, 2027", read as a calendar date (no time zone shift)
export function formatDate(iso: string) {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(year, month - 1, day).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

type ValidationIssue = { loc?: (string | number)[]; msg: string }

// FastAPI sends {detail: "text"} for our errors and {detail: [{loc, msg}]} for pydantic validation
function errorMessage(body: unknown): string | null {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return (detail as ValidationIssue[]).map(issue => {
      const field = String(issue.loc?.at(-1) ?? '').replaceAll('_', ' ')
      return field ? `${field[0].toUpperCase()}${field.slice(1)}: ${issue.msg}` : issue.msg
    }).join(' ')
  }
  return null
}

export const SESSION_EXPIRED_EVENT = 'hokie-rec-session-expired'

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

// Throws an Error whose message is safe to show the user
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')
  if (!['GET', 'HEAD', 'OPTIONS'].includes((init.method ?? 'GET').toUpperCase())) {
    headers.set('X-Requested-With', 'HokieRec')
  }
  let res: Response
  try {
    res = await fetch(API_URL + path, {
      ...init,
      credentials: 'include',
      headers,
    })
  } catch (e) {
    if (init.signal?.aborted) throw e
    throw new Error(`Can't reach the server at ${API_URL}. Is the backend running?`)
  }
  if (res.status === 204) return undefined as T
  const body = await res.json().catch(() => null)
  if (!res.ok) {
    // An anonymous session check is normal. A rejected write means the UI's
    // signed-in identity is stale and must be discarded everywhere.
    if (res.status === 401 && path !== '/api/auth/me' && path !== '/api/auth/login' && path !== '/api/auth/sign-up') {
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
    }
    throw new ApiError(errorMessage(body) ?? `Something went wrong (HTTP ${res.status}).`, res.status)
  }
  return body as T
}

export const unique = (values: string[]) => [...new Set(values)].sort()

// Builds "?a=1&b=2", skipping empty values
export function query(params: Record<string, string | number | null | undefined>) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

// GETs `path` whenever it changes; pass null to skip. `reload` refetches after a write.
export function useApi<T>(path: string | null) {
  const [version, setVersion] = useState(0)
  // `key` records which request the result belongs to, so loading is derived rather than stored
  const [result, setResult] = useState<{ key: string; data?: T; error: string }>({ key: '', error: '' })
  const key = `${path}#${version}`

  useEffect(() => {
    if (path === null) return
    const controller = new AbortController()
    api<T>(path, { signal: controller.signal }).then(
      data => setResult({ key, data, error: '' }),
      (e: Error) => {
        if (!controller.signal.aborted) setResult(prev => ({ key, data: prev.data, error: e.message }))
      },
    )
    return () => controller.abort()
  }, [path, key])

  const reload = useCallback(() => setVersion(v => v + 1), [])
  const loading = path !== null && result.key !== key
  return { data: result.data, error: loading ? '' : result.error, loading, reload }
}

export type Standing = {
  team_id: number
  team_name: string
  played: number
  wins: number
  losses: number
  ties: number
  points_for: number
  points_against: number
  point_diff: number
}

export type Participation = {
  league_id: number
  league_name: string
  sport_name: string
  term: string
  max_roster_size: number
  teams: number
  active_players: number
  pending_invites: number
  avg_roster_size: number | null
  games_played: number
  games_remaining: number
}

// One game with its latest score (GET /api/games). Team fields are null for an undecided playoff game.
export type Game = {
  game_id: number
  league_id: number
  league_name: string
  start_time: string
  end_time: string
  facility_name: string
  location: string
  home_team_id: number | null
  home_team_name: string | null
  away_team_id: number | null
  away_team_name: string | null
  playoff_round: number | null
  next_game_id: number | null
  status: string
  home_score: number | null
  away_score: number | null
  forfeit_team_id: number | null
}

// One of the signed-in official's assignments (GET /api/me/assignments)
export type Assignment = Game & { assignment_id: number; position: string; assignment_status: string; can_respond: boolean }
