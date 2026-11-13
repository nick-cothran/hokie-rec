// Both account forms preserve the intended destination without allowing external redirects.
import type { Role } from './api'

export function accountDestination(next: string | null, role: Role = 'player'): string {
  const fallback = role === 'official' ? '/schedule' : role === 'admin' ? '/admin/users' : '/teams'
  return next?.startsWith('/') && !next.startsWith('//') && !next.includes('\\') ? next : fallback
}

export function accountLink(path: '/sign-in' | '/sign-up', next: string | null): string {
  return next ? `${path}?next=${encodeURIComponent(accountDestination(next))}` : path
}
