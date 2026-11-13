import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, campusTime, useApi } from '../api'
import { useAuth } from '../auth'

type Kind = 'sports' | 'leagues' | 'facilities'
type Row = Record<string, string | number>
type Field = { name: string; label: string; type?: string; max?: number }
const fields: Record<Kind, Field[]> = {
  sports: [{ name: 'sport_name', label: 'Sport name', max: 50 }, { name: 'min_roster_size', label: 'Minimum roster size', type: 'number' }, { name: 'max_roster_size', label: 'Maximum roster size', type: 'number' }],
  facilities: [{ name: 'facility_name', label: 'Facility name', max: 60 }, { name: 'location', label: 'Location', max: 100 }],
  leagues: [{ name: 'sport_id', label: 'Sport', type: 'sport' }, { name: 'category', label: 'Category', max: 10 }, { name: 'skill_level', label: 'Skill level', max: 20 }, { name: 'term', label: 'Term', max: 20 }, { name: 'start_date', label: 'Season starts', type: 'date' }, { name: 'end_date', label: 'Season ends', type: 'date' }, { name: 'reg_open_at', label: 'Registration opens', type: 'datetime-local' }, { name: 'reg_close_at', label: 'Registration closes', type: 'datetime-local' }, { name: 'roster_lock_date', label: 'Roster lock date', type: 'date' }],
}
const ids: Record<Kind, string> = { sports: 'sport_id', leagues: 'league_id', facilities: 'facility_id' }
function localTime(value: string) {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(value)).replace(' ', 'T')
}
function SetupSection({ kind, sports, onChange }: { kind: Kind; sports: Row[]; onChange: () => void }) {
  const items = useApi<Row[]>(`/api/admin/setup/${kind}`)
  const [editing, setEditing] = useState<Row | null>(null)
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
  function select(row: Row | null) { setEditing(row); setRevision(v => v + 1); setError(''); setMessage('') }
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
  async function remove(row: Row) {
    if (!window.confirm('Delete this item? Items in use cannot be deleted.')) return
    setBusy(true); setError(''); setMessage('')
    try { await api(`/api/admin/setup/${kind}/${row[ids[kind]]}`, { method: 'DELETE' }); select(null); setMessage('Deleted.'); items.reload(); onChange() }
    catch (failure) { setError((failure as Error).message) } finally { setBusy(false) }
  }
  return <section className="panel"><h2>{kind[0].toUpperCase() + kind.slice(1)}</h2>
    {(error || items.error) && <p className="notice notice-error" role="alert">{error || items.error}</p>}{message && <p className="notice notice-success" role="status">{message}</p>}
    {items.loading && <p>Loading…</p>}
    <ul className="invite-list">{items.data?.map(row => <li key={row[ids[kind]]}><span>{kind === 'sports' ? row.sport_name : kind === 'facilities' ? `${row.facility_name} · ${row.location}` : `${sports.find(s => s.sport_id === row.sport_id)?.sport_name ?? 'Sport'} · ${row.category} · ${row.skill_level} · ${row.term}`}</span><span className="form-row"><button type="button" className="button button-outline button-small" disabled={busy} onClick={() => select(row)}>Edit</button><button type="button" className="button button-outline button-small" disabled={busy} onClick={() => remove(row)}>Delete</button></span></li>)}</ul>
    <h3 ref={formHeading} tabIndex={-1}>{editing ? 'Edit' : 'Add'} {kind === 'facilities' ? 'facility' : kind.slice(0, -1)}{editing && (kind === 'sports' ? `: ${editing.sport_name}` : kind === 'facilities' ? `: ${editing.facility_name}` : `: ${editing.category} · ${editing.skill_level} · ${editing.term}`)}</h3>
    {kind === 'leagues' && <p>Registration closes when the roster locks, even if the registration closing time is later.</p>}
    <form key={revision} className="form-stack" onSubmit={save}>{fields[kind].map(field => <label className="field" key={field.name}>{field.label}{field.type === 'sport' ? <select name={field.name} required defaultValue={editing?.sport_id ?? ''}><option value="">Choose a sport</option>{sports.map(s => <option key={s.sport_id} value={s.sport_id}>{s.sport_name}</option>)}</select> : <input name={field.name} type={field.type ?? 'text'} required maxLength={field.max} min={field.type === 'number' ? 0 : undefined} defaultValue={editing ? field.type === 'datetime-local' ? localTime(String(editing[field.name])) : editing[field.name] : ''} />}{field.type === 'datetime-local' && <small>Enter Blacksburg (Eastern) time.</small>}</label>)}
      <div className="form-row"><button className="button button-primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>{editing && <button className="button button-outline" type="button" onClick={() => select(null)}>Cancel edit</button>}</div></form>
  </section>
}
export default function AdminSetup() {
  const { user, loading } = useAuth()
  const sports = useApi<Row[]>(user?.role === 'admin' ? '/api/admin/setup/sports' : null)
  if (loading) return <main className="content-page"><p>Checking your session…</p></main>
  if (user?.role !== 'admin') return <main className="content-page"><h1>Administrators only</h1></main>
  return <main className="content-page"><Link className="back-link" to="/admin/users">← Administration</Link><div className="page-intro"><h1>Sports, leagues & facilities</h1><p>Set up the options available to teams and games. Items already in use cannot be deleted.</p></div>{sports.error && <p className="notice notice-error">{sports.error}</p>}{(['sports', 'leagues', 'facilities'] as Kind[]).map(kind => <SetupSection key={kind} kind={kind} sports={sports.data ?? []} onChange={sports.reload} />)}</main>
}
