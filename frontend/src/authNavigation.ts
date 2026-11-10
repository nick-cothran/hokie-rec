// Both account forms preserve the intended destination without allowing external redirects.
export function accountDestination(next: string | null): string {
  return next?.startsWith('/') && !next.startsWith('//') && !next.includes('\\') ? next : '/teams'
}

export function accountLink(path: '/sign-in' | '/sign-up', next: string | null): string {
  return next ? `${path}?next=${encodeURIComponent(accountDestination(next))}` : path
}
