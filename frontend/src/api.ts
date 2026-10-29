import { useCallback, useEffect, useState } from 'react'

export const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type Role = 'player' | 'official' | 'admin'

export type User = { user_id: number; first_name: string; last_name: string; role: Role }

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
  roster: RosterEntry[]
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

// Throws an Error whose message is safe to show the user
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(API_URL + path, {
      ...init,
      headers: init.body ? { 'Content-Type': 'application/json', ...init.headers } : init.headers,
    })
  } catch (e) {
    if (init.signal?.aborted) throw e
    throw new Error(`Can't reach the server at ${API_URL}. Is the backend running?`)
  }
  if (res.status === 204) return undefined as T
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new Error(errorMessage(body) ?? `Something went wrong (HTTP ${res.status}).`)
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
