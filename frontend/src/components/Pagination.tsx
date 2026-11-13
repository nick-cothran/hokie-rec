import '../styles/Pagination.css'

function Pagination({ page, pageCount, onPageChange }: { page: number; pageCount: number; onPageChange: (page: number) => void }) {
  if (pageCount <= 1) return null
  return (
    <nav className="pagination" aria-label="Results pages">
      <button className="button button-outline button-small" type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>Previous</button>
      <span aria-live="polite">Page {page} of {pageCount}</span>
      <button className="button button-outline button-small" type="button" disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>Next</button>
    </nav>
  )
}

export default Pagination
