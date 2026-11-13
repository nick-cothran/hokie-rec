import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import { api, campusTime, useApi } from '../api'

export type SetupKind = 'sports' | 'leagues' | 'facilities'
export type SetupRow = Record<string, string | number>
type Field = { name: string; label: string; type?: string; max?: number }
const fields: Record<SetupKind, Field[]> = {
  sports: [{ name: 'sport_name', label: 'Sport name', max: 50 }, { name: 'min_roster_size', label: 'Minimum roster size', type: 'number' }, { name: 'max_roster_size', label: 'Maximum roster size', type: 'number' }],
  facilities: [{ name: 'facility_name', label: 'Facility name', max: 60 }, { name: 'location', label: 'Location', max: 100 }],
  leagues: [{ name: 'sport_id', label: 'Sport', type: 'sport' }, { name: 'category', label: 'Category', max: 10 }, { name: 'skill_level', label: 'Skill level', max: 20 }, { name: 'term', label: 'Term', max: 20 }, { name: 'start_date', label: 'Season starts', type: 'date' }, { name: 'end_date', label: 'Season ends', type: 'date' }, { name: 'reg_open_at', label: 'Registration opens', type: 'datetime-local' }, { name: 'reg_close_at', label: 'Registration closes', type: 'datetime-local' }, { name: 'roster_lock_date', label: 'Roster lock date', type: 'date' }],
}
const ids: Record<SetupKind, string> = { sports: 'sport_id', leagues: 'league_id', facilities: 'facility_id' }
function localTime(value: string) {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value)).replace(' ', 'T')
}
export function SetupSection({ kind, sports, onChange }: { kind: SetupKind; sports: SetupRow[]; onChange: () => void }) {
  const items = useApi<SetupRow[]>(`/api/admin/setup/${kind}`)
  const [editing, setEditing] = useState<SetupRow | null>(null)
  const [revision, setRevision] = useState(0)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const formHeading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    if (editing && formHeading.current) {
      formHeading.current.scrollIntoView({ block: 'start' })
      formHeading.current.focus({ preventScroll: true })
    }
  }, [editing, revision])
  function select(row: SetupRow | null) { setEditing(row); setRevision(v => v + 1); setError(''); setMessage('') }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const body: Record<string, string | number> = {}
    try {
      for (const field of fields[kind]) {
        const value = String(data.get(field.name) ?? '').trim()
        if (field.type === 'number' || field.type === 'sport') body[field.name] = Number(value)
        else if (field.type === 'datetime-local') body[field.name] = campusTime(value).toISOString()
        else body[field.name] = value
      }
      setBusy(true); setError(''); setMessage('')
      await api(`/api/admin/setup/${kind}${editing ? `/${editing[ids[kind]]}` : ''}`, { method: editing ? 'PUT' : 'POST', body: JSON.stringify(body) })
      select(null); setMessage('Saved successfully.'); items.reload(); onChange()
    } catch (failure) { setError((failure as Error).message) } finally { setBusy(false) }
  }
  async function remove(row: SetupRow) {
    if (!window.confirm('Delete this item? Items in use cannot be deleted.')) return
    setBusy(true); setError(''); setMessage('')
    try { await api(`/api/admin/setup/${kind}/${row[ids[kind]]}`, { method: 'DELETE' }); select(null); setMessage('Deleted.'); items.reload(); onChange() }
    catch (failure) { setError((failure as Error).message) } finally { setBusy(false) }
  }
  const label = kind === 'sports' ? 'sport' : kind === 'facilities' ? 'facility' : 'league'
  const listTitle = kind[0].toUpperCase() + kind.slice(1)
  return <div className="admin-setup-cards">
    <section className="panel" aria-labelledby="setup-editor-heading">
      <h2 ref={formHeading} id="setup-editor-heading" tabIndex={-1}>{editing ? 'Edit' : 'Add'} {label}{editing && (kind === 'sports' ? `: ${editing.sport_name}` : kind === 'facilities' ? `: ${editing.facility_name}` : `: ${editing.category} · ${editing.skill_level} · ${editing.term}`)}</h2>
      {(error || items.error) && <p className="notice notice-error" role="alert">{error || items.error}</p>}
      {message && <p className="notice notice-success" role="status">{message}</p>}
      {kind === 'leagues' && <p>Registration closes when the roster locks, even if the registration closing time is later.</p>}
      <form key={revision} className={`form-stack setup-form${kind === 'leagues' ? ' setup-form-grid' : ''}`} onSubmit={save}>{fields[kind].map(field => <label className="field" key={field.name}>{field.label}{field.type === 'sport' ? <select name={field.name} required defaultValue={editing?.sport_id ?? ''}><option value="">Choose a sport</option>{sports.map(s => <option key={s.sport_id} value={s.sport_id}>{s.sport_name}</option>)}</select> : <input name={field.name} type={field.type ?? 'text'} required maxLength={field.max} min={field.type === 'number' ? 0 : undefined} defaultValue={editing ? field.type === 'datetime-local' ? localTime(String(editing[field.name])) : editing[field.name] : ''} />}{field.type === 'datetime-local' && <small>Enter Blacksburg (Eastern) time.</small>}</label>)}
        <div className="form-row"><button className="button button-primary" disabled={busy}>{busy ? 'Saving…' : `Save ${label}`}</button>{editing && <button className="button button-outline" type="button" onClick={() => select(null)}>Cancel edit</button>}</div></form>
    </section>
    <section className="panel" aria-labelledby="setup-list-heading">
      <h2 id="setup-list-heading">{listTitle}</h2>
      {items.loading && <p className="loading">Loading {kind}…</p>}
      {items.data?.length === 0 && <p>No {kind} yet. Add one above.</p>}
      {!!items.data?.length && <ul className="invite-list">{items.data.map(row => <li key={row[ids[kind]]}><span>{kind === 'sports' ? row.sport_name : kind === 'facilities' ? `${row.facility_name} · ${row.location}` : `${sports.find(s => s.sport_id === row.sport_id)?.sport_name ?? 'Sport'} · ${row.category} · ${row.skill_level} · ${row.term}`}</span><span className="form-row"><button type="button" className="button button-outline button-small" disabled={busy} onClick={() => select(row)}>Edit</button><button type="button" className="button button-outline button-small" disabled={busy} onClick={() => remove(row)}>Delete</button></span></li>)}</ul>}
    </section>
  </div>
}
export default function AdminSetup() {
  return <Navigate to="/admin/users?tab=sports" replace />
}
