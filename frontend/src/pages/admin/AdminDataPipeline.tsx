import { useState, useRef } from 'react'
import {
  ClipboardDocumentListIcon,
  CloudArrowUpIcon,
  CheckCircleIcon,
  ExclamationCircleIcon,
  MinusCircleIcon,
  TableCellsIcon,
  FunnelIcon,
  AdjustmentsHorizontalIcon,
  DocumentMagnifyingGlassIcon,
  ArrowDownTrayIcon,
  PlayIcon,
  TrashIcon,
  InformationCircleIcon,
} from '@heroicons/react/20/solid'
import AdminLayout from '@/components/admin/AdminLayout'

// ── Design tokens ─────────────────────────────────────────────────────────────
const R  = '#CC0000'
const RD = '#990000'
const CARD: React.CSSProperties = {
  background: '#ffffff',
  borderRadius: '14px',
  border: '1px solid #e2e4e9',
  boxShadow: '0 2px 12px rgba(0,0,0,0.07)',
  fontFamily: "'Segoe UI', system-ui, sans-serif",
}

// ── Types ─────────────────────────────────────────────────────────────────────
type StageStatus = 'idle' | 'ready' | 'running' | 'done' | 'error'
type DatasetTab  = 'crsp' | 'ntsa'

interface PipelineStage {
  id: string
  label: string
  description: string
  icon: React.ReactNode
}

// ── Pipeline stage definitions ────────────────────────────────────────────────
const CRSP_STAGES: PipelineStage[] = [
  {
    id: 'parse',
    label: 'Parse & Load',
    description: 'Read the raw CRSP Excel/CSV file and load it into memory.',
    icon: <TableCellsIcon style={{ width: 16, height: 16 }} />,
  },
  {
    id: 'validate',
    label: 'Validate Schema',
    description: 'Check that required columns (make, model, year, capacity_ah, technology) are present and non-empty.',
    icon: <DocumentMagnifyingGlassIcon style={{ width: 16, height: 16 }} />,
  },
  {
    id: 'normalize',
    label: 'Normalize Fields',
    description: 'Uppercase make/model, strip whitespace, cast numeric fields, unify technology labels (e.g. "EFB" → "EFB").',
    icon: <AdjustmentsHorizontalIcon style={{ width: 16, height: 16 }} />,
  },
  {
    id: 'deduplicate',
    label: 'Deduplicate',
    description: 'Remove duplicate rows by (make, model, year, battery_code). Last occurrence wins.',
    icon: <FunnelIcon style={{ width: 16, height: 16 }} />,
  },
  {
    id: 'enrich',
    label: 'Enrich Years',
    description: 'Expand year-range entries (e.g. 2015–2019) into individual yearly rows.',
    icon: <ClipboardDocumentListIcon style={{ width: 16, height: 16 }} />,
  },
  {
    id: 'export',
    label: 'Export / Commit',
    description: 'Write the cleaned dataset to the database or export as a normalised CSV.',
    icon: <ArrowDownTrayIcon style={{ width: 16, height: 16 }} />,
  },
]

const NTSA_STAGES: PipelineStage[] = [
  {
    id: 'parse',
    label: 'Parse & Load',
    description: 'Read the raw NTSA vehicle registration CSV/Excel file into memory.',
    icon: <TableCellsIcon style={{ width: 16, height: 16 }} />,
  },
  {
    id: 'validate',
    label: 'Validate Schema',
    description: 'Verify required columns (plate_number, make, model, year_of_manufacture, fuel_type) exist and are non-empty.',
    icon: <DocumentMagnifyingGlassIcon style={{ width: 16, height: 16 }} />,
  },
  {
    id: 'normalize',
    label: 'Normalize Fields',
    description: 'Standardise plate formats, uppercase make/model, normalise fuel type labels, cast year as integer.',
    icon: <AdjustmentsHorizontalIcon style={{ width: 16, height: 16 }} />,
  },
  {
    id: 'filter',
    label: 'Filter Invalid Records',
    description: 'Drop records with year < 1970 or > current year, unknown fuel types, or clearly erroneous plate numbers.',
    icon: <FunnelIcon style={{ width: 16, height: 16 }} />,
  },
  {
    id: 'deduplicate',
    label: 'Deduplicate',
    description: 'Remove duplicate registrations by plate_number, keeping the most recent record.',
    icon: <ClipboardDocumentListIcon style={{ width: 16, height: 16 }} />,
  },
  {
    id: 'merge',
    label: 'Merge with CRSP',
    description: 'Left-join NTSA vehicles against the cleaned CRSP dataset on (make, model, year) to attach battery recommendations.',
    icon: <AdjustmentsHorizontalIcon style={{ width: 16, height: 16 }} />,
  },
  {
    id: 'export',
    label: 'Export / Commit',
    description: 'Write the enriched NTSA dataset to the database or export as a normalised CSV.',
    icon: <ArrowDownTrayIcon style={{ width: 16, height: 16 }} />,
  },
]

// ── Helpers ────────────────────────────────────────────────────────────────────
function statusColor(s: StageStatus): string {
  if (s === 'done')    return '#22c55e'
  if (s === 'running') return '#f59e0b'
  if (s === 'error')   return R
  if (s === 'ready')   return '#3b82f6'
  return '#d1d5db'
}

function statusBg(s: StageStatus): string {
  if (s === 'done')    return '#f0fdf4'
  if (s === 'running') return '#fffbeb'
  if (s === 'error')   return '#fff5f5'
  if (s === 'ready')   return '#eff6ff'
  return '#f9fafb'
}

function StatusIcon({ status }: { status: StageStatus }) {
  const style = { width: 16, height: 16 }
  if (status === 'done')    return <CheckCircleIcon   style={{ ...style, color: '#22c55e' }} />
  if (status === 'error')   return <ExclamationCircleIcon style={{ ...style, color: R }} />
  if (status === 'running') return <ArrowSpinner />
  return <MinusCircleIcon style={{ ...style, color: '#d1d5db' }} />
}

function ArrowSpinner() {
  return (
    <svg
      width="16" height="16" viewBox="0 0 16 16" fill="none"
      style={{ animation: 'spin 1s linear infinite' }}
    >
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <circle cx="8" cy="8" r="6" stroke="#f59e0b" strokeWidth="2.5" strokeLinecap="round"
        strokeDasharray="28" strokeDashoffset="10" />
    </svg>
  )
}

// ── DropZone ──────────────────────────────────────────────────────────────────
function DropZone({
  label,
  accept,
  file,
  onFile,
  onClear,
}: {
  label: string
  accept: string
  file: File | null
  onFile: (f: File) => void
  onClear: () => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const dropped = e.dataTransfer.files[0]
    if (dropped) onFile(dropped)
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0]
    if (picked) onFile(picked)
  }

  const border = dragging ? `2px dashed ${R}` : file ? '2px dashed #22c55e' : '2px dashed #d1d5db'
  const bg     = dragging ? '#fff5f5' : file ? '#f0fdf4' : '#f9fafb'

  return (
    <div
      style={{ borderRadius: 12, border, background: bg, padding: '1.75rem 1.5rem', textAlign: 'center', cursor: 'pointer', transition: 'all 0.2s' }}
      onDragOver={e => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => !file && inputRef.current?.click()}
    >
      <input ref={inputRef} type="file" accept={accept} style={{ display: 'none' }} onChange={handleChange} />
      {file ? (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.75rem' }}>
          <CheckCircleIcon style={{ width: 22, height: 22, color: '#22c55e', flexShrink: 0 }} />
          <div style={{ textAlign: 'left' }}>
            <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'rgba(17,24,39,0.88)' }}>{file.name}</div>
            <div style={{ fontSize: '0.7rem', color: 'rgba(107,114,128,0.8)' }}>
              {(file.size / 1024).toFixed(1)} KB · {file.type || 'unknown type'}
            </div>
          </div>
          <button
            onClick={e => { e.stopPropagation(); onClear() }}
            style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: 'rgba(107,114,128,0.6)', padding: 4, borderRadius: 6 }}
            title="Remove file"
          >
            <TrashIcon style={{ width: 15, height: 15 }} />
          </button>
        </div>
      ) : (
        <>
          <CloudArrowUpIcon style={{ width: 32, height: 32, color: '#d1d5db', marginBottom: '0.6rem' }} />
          <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'rgba(17,24,39,0.7)' }}>{label}</div>
          <div style={{ fontSize: '0.7rem', color: 'rgba(107,114,128,0.6)', marginTop: '0.3rem' }}>
            Drag & drop or <span style={{ color: R, fontWeight: 600 }}>browse</span>
          </div>
          <div style={{ fontSize: '0.65rem', color: 'rgba(107,114,128,0.45)', marginTop: '0.3rem' }}>{accept}</div>
        </>
      )}
    </div>
  )
}

// ── StageCard ─────────────────────────────────────────────────────────────────
function StageCard({
  stage,
  status,
  index,
  total,
  log,
}: {
  stage: PipelineStage
  status: StageStatus
  index: number
  total: number
  log?: string
}) {
  return (
    <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-start' }}>
      {/* Timeline connector */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
        <div style={{
          width: 32, height: 32, borderRadius: '50%',
          background: statusBg(status),
          border: `2px solid ${statusColor(status)}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '0.7rem', fontWeight: 800, color: statusColor(status),
          flexShrink: 0,
        }}>
          {index + 1}
        </div>
        {index < total - 1 && (
          <div style={{ width: 2, flex: 1, minHeight: 24, background: statusColor(status), opacity: status === 'idle' ? 0.2 : 0.5, marginTop: 2 }} />
        )}
      </div>

      {/* Card body */}
      <div style={{
        ...CARD,
        flex: 1,
        padding: '0.85rem 1rem',
        borderLeft: `4px solid ${statusColor(status)}`,
        marginBottom: index < total - 1 ? '0.5rem' : 0,
        background: statusBg(status),
        transition: 'all 0.2s',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ color: statusColor(status) }}>{stage.icon}</span>
            <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'rgba(17,24,39,0.88)' }}>{stage.label}</span>
          </div>
          <StatusIcon status={status} />
        </div>
        <p style={{ margin: '0.4rem 0 0', fontSize: '0.72rem', color: 'rgba(107,114,128,0.85)', lineHeight: 1.5 }}>
          {stage.description}
        </p>
        {log && (
          <div style={{ marginTop: '0.5rem', background: 'rgba(17,24,39,0.04)', borderRadius: 6, padding: '0.4rem 0.6rem', fontSize: '0.68rem', fontFamily: 'monospace', color: status === 'error' ? R : 'rgba(17,24,39,0.7)', whiteSpace: 'pre-wrap' }}>
            {log}
          </div>
        )}
      </div>
    </div>
  )
}

// ── SummaryBadge ──────────────────────────────────────────────────────────────
function SummaryBadge({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div style={{ ...CARD, padding: '0.75rem 1rem', textAlign: 'center', minWidth: 110 }}>
      <div style={{ fontSize: '1.4rem', fontWeight: 900, color: color ?? 'rgba(17,24,39,0.88)', letterSpacing: '-0.02em' }}>{value}</div>
      <div style={{ fontSize: '0.65rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'rgba(107,114,128,0.7)', marginTop: '0.2rem' }}>{label}</div>
    </div>
  )
}

// ── PipelineTab ───────────────────────────────────────────────────────────────
function PipelineTab({
  dataset,
  stages,
  fileAccept,
  dropLabel,
  info,
}: {
  dataset: 'CRSP' | 'NTSA'
  stages: PipelineStage[]
  fileAccept: string
  dropLabel: string
  info: string
}) {
  const [file,     setFile]     = useState<File | null>(null)
  const [statuses, setStatuses] = useState<StageStatus[]>(() => stages.map(() => 'idle'))
  const [logs,     setLogs]     = useState<(string | undefined)[]>(() => stages.map(() => undefined))
  const [running,  setRunning]  = useState(false)
  const [summary,  setSummary]  = useState<{ total: number; clean: number; rejected: number; dupes: number } | null>(null)

  // Simulated demo run — replace with real API calls later
  function handleRun() {
    if (!file || running) return
    setRunning(true)
    setSummary(null)
    const fresh: StageStatus[] = stages.map(() => 'idle')
    setStatuses(fresh)
    setLogs(stages.map(() => undefined))

    let current = 0

    function advance() {
      if (current >= stages.length) {
        setRunning(false)
        // Show a mock summary
        setSummary({ total: 0, clean: 0, rejected: 0, dupes: 0 })
        return
      }
      setStatuses(prev => {
        const next = [...prev]
        next[current] = 'running'
        return next
      })
      // Each stage "runs" for 1–1.5 s in the demo
      const delay = 900 + Math.random() * 600
      setTimeout(() => {
        setStatuses(prev => {
          const next = [...prev]
          next[current] = 'done'
          return next
        })
        setLogs(prev => {
          const next = [...prev]
          next[current] = stageDemoLog(stages[current].id, dataset)
          return next
        })
        current++
        advance()
      }, delay)
    }

    advance()
  }

  function handleReset() {
    setFile(null)
    setStatuses(stages.map(() => 'idle'))
    setLogs(stages.map(() => undefined))
    setSummary(null)
    setRunning(false)
  }

  const allDone = statuses.every(s => s === 'done')
  const anyError = statuses.some(s => s === 'error')
  const currentStageIdx = statuses.findIndex(s => s === 'running')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

      {/* Info banner */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.6rem', background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 10, padding: '0.75rem 1rem' }}>
        <InformationCircleIcon style={{ width: 16, height: 16, color: '#3b82f6', flexShrink: 0, marginTop: 1 }} />
        <p style={{ margin: 0, fontSize: '0.75rem', color: '#1d4ed8', lineHeight: 1.6 }}>{info}</p>
      </div>

      {/* Upload + controls row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '1rem', alignItems: 'start' }}>
        <DropZone
          label={dropLabel}
          accept={fileAccept}
          file={file}
          onFile={setFile}
          onClear={handleReset}
        />

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', paddingTop: 2 }}>
          <button
            onClick={handleRun}
            disabled={!file || running}
            style={{
              display: 'flex', alignItems: 'center', gap: '0.45rem',
              fontSize: '0.82rem', fontWeight: 700,
              padding: '0.6rem 1.1rem', borderRadius: 10, border: 'none', cursor: !file || running ? 'not-allowed' : 'pointer',
              background: !file || running ? '#e2e4e9' : R,
              color: !file || running ? 'rgba(107,114,128,0.7)' : '#fff',
              transition: 'background 0.15s',
              whiteSpace: 'nowrap',
            }}
            onMouseEnter={e => { if (file && !running) e.currentTarget.style.background = RD }}
            onMouseLeave={e => { if (file && !running) e.currentTarget.style.background = R }}
          >
            <PlayIcon style={{ width: 14, height: 14 }} />
            {running ? `Running…` : 'Run Pipeline'}
          </button>
          <button
            onClick={handleReset}
            style={{
              display: 'flex', alignItems: 'center', gap: '0.45rem',
              fontSize: '0.75rem', fontWeight: 600,
              padding: '0.5rem 1rem', borderRadius: 10,
              border: '1px solid #e2e4e9', cursor: 'pointer',
              background: '#fff', color: 'rgba(107,114,128,0.8)',
              transition: 'all 0.15s', whiteSpace: 'nowrap',
            }}
          >
            <TrashIcon style={{ width: 13, height: 13 }} /> Reset
          </button>
        </div>
      </div>

      {/* Progress overview pill */}
      {(running || allDone || anyError) && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', padding: '0.5rem 1rem', background: '#fff', border: '1px solid #e2e4e9', borderRadius: 99, fontSize: '0.75rem', fontWeight: 600, color: anyError ? R : allDone ? '#15803d' : '#b45309' }}>
          {anyError
            ? <><ExclamationCircleIcon style={{ width: 14, height: 14 }} /> Pipeline stopped — fix errors and retry</>
            : allDone
            ? <><CheckCircleIcon style={{ width: 14, height: 14 }} /> All {stages.length} stages completed successfully</>
            : <><ArrowSpinner /> Stage {(currentStageIdx + 1)} of {stages.length} — {stages[currentStageIdx]?.label}</>
          }
        </div>
      )}

      {/* Summary cards */}
      {allDone && summary && (
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
          <SummaryBadge label="Total Rows"  value="—" />
          <SummaryBadge label="Clean"       value="—" color="#22c55e" />
          <SummaryBadge label="Rejected"    value="—" color={R} />
          <SummaryBadge label="Duplicates"  value="—" color="#f59e0b" />
          <SummaryBadge label="Exported"    value="—" color="#3b82f6" />
        </div>
      )}

      {/* Pipeline stages */}
      <div style={{ ...CARD, padding: '1.25rem 1.25rem 1rem' }}>
        <h3 style={{ margin: '0 0 1rem', fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.8)' }}>
          Pipeline Stages
        </h3>
        <div>
          {stages.map((stage, idx) => (
            <StageCard
              key={stage.id}
              stage={stage}
              status={statuses[idx]}
              index={idx}
              total={stages.length}
              log={logs[idx]}
            />
          ))}
        </div>
      </div>

      {/* Export button (enabled when done) */}
      {allDone && (
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button
            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.82rem', fontWeight: 700, padding: '0.65rem 1.25rem', borderRadius: 10, border: 'none', cursor: 'pointer', background: '#1d4ed8', color: '#fff' }}
          >
            <ArrowDownTrayIcon style={{ width: 15, height: 15 }} /> Download Cleaned {dataset} CSV
          </button>
          <button
            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.82rem', fontWeight: 700, padding: '0.65rem 1.25rem', borderRadius: 10, border: '1px solid #e2e4e9', cursor: 'pointer', background: '#fff', color: 'rgba(17,24,39,0.8)' }}
          >
            <ClipboardDocumentListIcon style={{ width: 15, height: 15 }} /> View Full Report
          </button>
        </div>
      )}
    </div>
  )
}

// ── Demo log messages per stage ───────────────────────────────────────────────
function stageDemoLog(stageId: string, dataset: 'CRSP' | 'NTSA'): string {
  const logs: Record<string, Record<string, string>> = {
    CRSP: {
      parse:       '✓ Loaded file successfully\n  → Backend will read the uploaded file here',
      validate:    '✓ Schema check passed\n  → Required columns will be verified here',
      normalize:   '✓ Normalization complete\n  → Fields will be standardised here',
      deduplicate: '✓ Deduplication complete\n  → Duplicate rows will be removed here',
      enrich:      '✓ Year enrichment complete\n  → Year ranges will be expanded here',
      export:      '✓ Ready to commit\n  → Clean data will be written to DB here',
    },
    NTSA: {
      parse:       '✓ Loaded file successfully\n  → Backend will read the uploaded file here',
      validate:    '✓ Schema check passed\n  → Required columns will be verified here',
      normalize:   '✓ Normalization complete\n  → Plate numbers & fuel types standardised here',
      filter:      '✓ Invalid records filtered\n  → Out-of-range years & bad plates removed here',
      deduplicate: '✓ Deduplication complete\n  → Duplicate plates removed here',
      merge:       '✓ CRSP merge complete\n  → Battery recommendations attached here',
      export:      '✓ Ready to commit\n  → Enriched data will be written to DB here',
    },
  }
  return logs[dataset]?.[stageId] ?? '✓ Stage complete'
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function AdminDataPipeline() {
  const [activeTab, setActiveTab] = useState<DatasetTab>('crsp')

  function tabStyle(tab: DatasetTab): React.CSSProperties {
    const active = activeTab === tab
    return {
      display: 'flex', alignItems: 'center', gap: '0.45rem',
      padding: '0.55rem 1.25rem', borderRadius: '99px',
      fontSize: '0.82rem', fontWeight: 700, cursor: 'pointer', border: 'none',
      background: active ? R : '#fff',
      color: active ? '#fff' : 'rgba(17,24,39,0.65)',
      boxShadow: active ? '0 2px 8px rgba(204,0,0,0.25)' : 'none',
      transition: 'all 0.15s',
    }
  }

  return (
    <AdminLayout>

      <main style={{ maxWidth: '960px', margin: '0 auto', padding: '2rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>

        {/* Page header */}
        <div style={{ ...CARD, padding: '1.25rem 1.5rem', display: 'flex', alignItems: 'center', gap: '1.25rem', borderLeft: `5px solid ${R}` }}>
          <div style={{ width: 42, height: 42, borderRadius: 12, background: '#fff5f5', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <FunnelIcon style={{ width: 22, height: 22, color: R }} />
          </div>
          <div>
            <div style={{ fontSize: '1.05rem', fontWeight: 800, color: 'rgba(17,24,39,0.88)' }}>Vehicle Dataset Cleaning Pipeline</div>
            <div style={{ fontSize: '0.78rem', color: 'rgba(107,114,128,0.85)', marginTop: '0.2rem' }}>
              Upload a raw CRSP or NTSA dataset to validate, normalize, deduplicate, and export clean vehicle data.
            </div>
          </div>
        </div>

        {/* Dataset tabs */}
        <div style={{ ...CARD, padding: '1.25rem 1.5rem' }}>
          {/* Tab switcher */}
          <div style={{ display: 'flex', gap: '0.5rem', background: '#f4f5f7', padding: '0.3rem', borderRadius: 99, width: 'fit-content', marginBottom: '1.5rem' }}>
            <button style={tabStyle('crsp')} onClick={() => setActiveTab('crsp')}>
              <TableCellsIcon style={{ width: 14, height: 14 }} /> CRSP Dataset
            </button>
            <button style={tabStyle('ntsa')} onClick={() => setActiveTab('ntsa')}>
              <DocumentMagnifyingGlassIcon style={{ width: 14, height: 14 }} /> NTSA Dataset
            </button>
          </div>

          {activeTab === 'crsp' ? (
            <PipelineTab
              key="crsp"
              dataset="CRSP"
              stages={CRSP_STAGES}
              fileAccept=".xlsx,.xls,.csv"
              dropLabel="Drop your CRSP vehicles dataset here"
              info="The CRSP pipeline validates make/model/year/battery fields, normalises technology labels, expands year ranges, and deduplicates rows before committing clean records to the database."
            />
          ) : (
            <PipelineTab
              key="ntsa"
              dataset="NTSA"
              stages={NTSA_STAGES}
              fileAccept=".xlsx,.xls,.csv"
              dropLabel="Drop your NTSA vehicle registration dataset here"
              info="The NTSA pipeline validates plate numbers, normalises fuel types and make/model fields, filters invalid year-of-manufacture values, deduplicates by plate number, and merges battery recommendations from the cleaned CRSP data."
            />
          )}
        </div>

      </main>
    </AdminLayout>
  )
}
