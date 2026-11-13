import '../styles/ViewTabs.css'

type View = 'mine' | 'all'

function ViewTabs({ label, personalLabel, allLabel, value, onChange }: {
  label: string
  personalLabel: string
  allLabel: string
  value: View
  onChange: (view: View) => void
}) {
  return (
    <div className="view-tabs" role="group" aria-label={label}>
      <button type="button" className="view-tab" aria-pressed={value === 'mine'} onClick={() => onChange('mine')}>{personalLabel}</button>
      <button type="button" className="view-tab" aria-pressed={value === 'all'} onClick={() => onChange('all')}>{allLabel}</button>
    </div>
  )
}

export default ViewTabs
