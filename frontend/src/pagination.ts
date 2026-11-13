const PAGE_SIZE = 10

export function paginate<T>(items: T[], requestedPage: string | null) {
  const parsed = requestedPage && /^[1-9]\d*$/.test(requestedPage) ? Number(requestedPage) : 1
  const pageCount = Math.max(1, Math.ceil(items.length / PAGE_SIZE))
  const page = Number.isSafeInteger(parsed) ? Math.min(parsed, pageCount) : 1
  const start = (page - 1) * PAGE_SIZE
  return { page, pageCount, start, end: Math.min(start + PAGE_SIZE, items.length), items: items.slice(start, start + PAGE_SIZE) }
}
