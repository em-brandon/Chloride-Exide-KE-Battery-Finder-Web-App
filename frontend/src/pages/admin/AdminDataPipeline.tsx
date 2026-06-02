import { useState, useRef, useEffect, useCallback } from 'react'
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
  ArrowPathIcon,
  PlayIcon,
  TrashIcon,
  InformationCircleIcon,
  GlobeAltIcon,
  StopIcon,
  PauseIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  MagnifyingGlassIcon,
  ClockIcon,
  ArchiveBoxIcon,
  ServerStackIcon,
  XMarkIcon,
} from '@heroicons/react/20/solid'
import AdminLayout from '@/components/admin/AdminLayout'
import {
  runWebValidatePipeline,
  getWebValidateStatus,
  pauseWebValidate,
  resumeWebValidate,
  cancelWebValidate,
  getPipelineQuotas,
  getWebValidateCoverage,
  resetWebValidateCache,
  getWebValidateProviders,
  getWebValidateMatched,
  getStagingArea,
  getStagingPreCommit,
  commitStagingArea,
  discardStagingArea,
  patchStagingRow,
  getValidationVersions,
  getVersionChangelog,
  revertVersion,
  getPipelineStaleness,
  type WebValidateStatus,
  type RevertVersionResult,
  type QuotaInfo,
  type CoverageInfo,
  type ProviderInfo,
  type MatchedVehiclesResponse,
  type StagingAreaResponse,
  type StagingRow,
  type ConflictResolution,
  type CommitStagingResult,
  type ValidationVersion,
  type VersionChangelogResponse,
  type StalenessInfo,
} from '@/lib/adminApi'

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
type DatasetTab  = 'crsp' | 'ntsa' | 'webvalidate'

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

// ── Web Validate helpers ──────────────────────────────────────────────────────

const PROVIDER_LABELS: Record<string, string> = {
  duckduckgo: 'DuckDuckGo',
  google_cse: 'Google CSE',
  tavily:     'Tavily',
}

function QuotaBar({ pct, quota_limit }: { pct: number; quota_limit: number }) {
  if (quota_limit === -1) {
    return (
      <div style={{ fontSize: '0.65rem', color: '#22c55e', fontWeight: 700 }}>unlimited</div>
    )
  }
  const color = pct >= 90 ? R : pct >= 70 ? '#f59e0b' : '#22c55e'
  return (
    <div style={{ width: '100%', background: '#e2e4e9', borderRadius: 99, height: 6, overflow: 'hidden', marginTop: 4 }}>
      <div style={{ width: `${Math.min(pct, 100)}%`, background: color, height: '100%', borderRadius: 99, transition: 'width 0.3s' }} />
    </div>
  )
}

function QuotaCard({ info }: { info: QuotaInfo }) {
  const pct = info.pct_used
  const color = pct >= 90 ? R : pct >= 70 ? '#f59e0b' : '#22c55e'
  const limitLabel = info.quota_limit === -1 ? '∞' : info.quota_limit.toLocaleString()
  return (
    <div style={{ ...CARD, padding: '0.85rem 1rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.4rem' }}>
        <GlobeAltIcon style={{ width: 13, height: 13, color: '#6b7280', flexShrink: 0 }} />
        <span style={{ fontSize: '0.72rem', fontWeight: 700, color: 'rgba(17,24,39,0.8)' }}>
          {PROVIDER_LABELS[info.provider] ?? info.provider}
        </span>
      </div>
      <div style={{ fontSize: '1.05rem', fontWeight: 900, color, letterSpacing: '-0.02em' }}>
        {info.calls_made.toLocaleString()}
        <span style={{ fontSize: '0.65rem', fontWeight: 500, color: 'rgba(107,114,128,0.7)', marginLeft: 2 }}>
          / {limitLabel}
        </span>
      </div>
      <QuotaBar pct={pct} quota_limit={info.quota_limit} />
    </div>
  )
}

const PROVIDER_BADGE: Record<string, string> = {
  '[ddg]':        'DuckDuckGo',
  '[google_cse]': 'Google CSE',
  '[tavily]':     'Tavily',
  '[prefetch]':   'Web Pre-fetch',
}

function LogLine({ raw }: { raw: string }) {
  const isError   = /\[error\]|error:/i.test(raw)
  const isWarning = /\[warn\]|warning:/i.test(raw)
  const isSuccess = /✓|done|complete|found \d/i.test(raw)
  const isPhase   = /phase \d|starting|finished|pipeline/i.test(raw)

  let text = raw
  let badge: string | null = null
  for (const [prefix, label] of Object.entries(PROVIDER_BADGE)) {
    if (raw.toLowerCase().startsWith(prefix.toLowerCase())) {
      badge = label
      text = raw.slice(prefix.length).trim()
      break
    }
  }

  const dotColor  = isError ? R : isWarning ? '#f59e0b' : isSuccess ? '#22c55e' : '#d1d5db'
  const textColor = isError ? R : isPhase ? '#1d4ed8' : '#374151'
  const bg        = isPhase ? '#f0f7ff' : 'transparent'
  const fw        = isPhase ? 700 : 400

  return (
    <div style={{
      display: 'flex', alignItems: 'baseline', gap: '0.5rem',
      padding: '0.2rem 1rem',
      background: bg,
      borderLeft: isPhase ? '3px solid #bfdbfe' : '3px solid transparent',
    }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: dotColor, flexShrink: 0, marginTop: 5, display: 'inline-block' }} />
      {badge && (
        <span style={{
          fontSize: '0.62rem', fontWeight: 700,
          background: '#eff6ff', color: '#3b82f6',
          borderRadius: 99, padding: '0.05rem 0.4rem',
          whiteSpace: 'nowrap', flexShrink: 0,
        }}>
          {badge}
        </span>
      )}
      <span style={{ color: textColor, fontWeight: fw, flex: 1 }}>{text}</span>
    </div>
  )
}

function LogPanel({ lines }: { lines: string[] }) {
  const containerRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [lines])
  return (
    <div style={{ ...CARD, overflow: 'hidden' }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: '0.4rem',
        padding: '0.6rem 1rem', borderBottom: '1px solid #e2e4e9',
        background: '#f9fafb',
      }}>
        <ClipboardDocumentListIcon style={{ width: 13, height: 13, color: '#9ca3af' }} />
        <span style={{ fontSize: '0.65rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', color: '#9ca3af' }}>
          Pipeline Log
        </span>
      </div>
      <div
        ref={containerRef}
        style={{
          maxHeight: 240, overflowY: 'auto',
          padding: '0.5rem 0',
          fontFamily: "'Segoe UI', system-ui, sans-serif",
          fontSize: '0.76rem',
          lineHeight: 1.6,
        }}
      >
        {lines.length === 0
          ? <div style={{ padding: '0.5rem 1rem', color: '#9ca3af', fontStyle: 'italic' }}>Waiting for pipeline output…</div>
          : lines.map((l, i) => <LogLine key={i} raw={l} />)
        }
      </div>
    </div>
  )
}

const COVERAGE_PAGE_SIZE = 50

function WebValidateLoadingOverlay() {
  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: '#fff',
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '1.5rem',
    }}>
      <svg width="64" height="64" viewBox="0 0 24 24" fill="#CC0000" xmlns="http://www.w3.org/2000/svg" style={{ animation: 'loaderPulse 1.2s ease-in-out infinite' }}>
        <path fillRule="evenodd" d="M14.615 1.595a.75.75 0 0 1 .359.852L12.982 9.75h7.268a.75.75 0 0 1 .548 1.262l-10.5 11.25a.75.75 0 0 1-1.272-.71l1.992-7.302H3.75a.75.75 0 0 1-.548-1.262l10.5-11.25a.75.75 0 0 1 .913-.143Z" clipRule="evenodd" />
      </svg>
      <span style={{ fontSize: '1.05rem', fontWeight: 600, color: '#374151', fontFamily: "'Segoe UI',system-ui,sans-serif" }}>Loading…</span>
    </div>
  )
}

function formatEta(seconds: number): string {
  if (!isFinite(seconds) || seconds <= 0) return '—'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}h ${m}m remaining`
  if (m > 0) return `${m}m ${s}s remaining`
  return `${s}s remaining`
}

function Phase1ElapsedTimer({ startedAt }: { startedAt: string }) {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const base = new Date(startedAt).getTime()
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - base) / 1000)), 1000)
    return () => clearInterval(id)
  }, [startedAt])
  const h = Math.floor(elapsed / 3600)
  const m = Math.floor((elapsed % 3600) / 60)
  const s = elapsed % 60
  const label = h > 0
    ? `${h}h ${m}m ${s}s elapsed`
    : m > 0
      ? `${m}m ${s}s elapsed`
      : `${s}s elapsed`
  return <span style={{ fontSize: '0.65rem', color: '#6b7280' }}>{label}</span>
}

function WebValidateTab() {
  const [tabLoading, setTabLoading]       = useState(true)
  const [status, setStatus]               = useState<WebValidateStatus | null>(null)
  const [quotas, setQuotas]               = useState<QuotaInfo[]>([])
  const [coverage, setCoverage]           = useState<CoverageInfo | null>(null)
  const [coverageLoading, setCoverageLoading] = useState(false)
  const [providerInfo, setProviderInfo]   = useState<ProviderInfo[]>([])
  const [enabledProviders, setEnabledProviders] = useState<Set<string>>(
    new Set(['duckduckgo'])
  )
  const [actionError, setActionError]     = useState<string | null>(null)
  const [loadingRun, setLoadingRun]       = useState(false)
  const [actionInProgress, setActionInProgress] = useState<'pause' | 'resume' | 'cancel' | null>(null)
  const [isStopping, setIsStopping] = useState(false)
  const [loadingQuotas, setLoadingQuotas] = useState(false)
  const [loadingCacheReset, setLoadingCacheReset] = useState(false)
  const [cacheResetMsg, setCacheResetMsg] = useState<string | null>(null)
  const [coveragePage, setCoveragePage]   = useState(1)
  const [coverageSearch, setCoverageSearch] = useState('')
  const [showUnmatched, setShowUnmatched] = useState(false)
  const [showMatched, setShowMatched]         = useState(false)
  const [matchedPage, setMatchedPage]         = useState(1)
  const [matchedSearch, setMatchedSearch]     = useState('')
  const [matchedData, setMatchedData]         = useState<MatchedVehiclesResponse | null>(null)
  const [matchedLoading, setMatchedLoading]   = useState(false)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const matchedDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Staging area state
  const [stagingInfo, setStagingInfo]             = useState<StagingAreaResponse | null>(null)
  const [stagingFilter, setStagingFilter]         = useState<'all' | 'valid' | 'invalid' | 'conflicts'>('all')
  const [stagingPage, setStagingPage]             = useState(1)
  const [stagingLoading, setStagingLoading]       = useState(false)
  const [stagingToast, setStagingToast]           = useState<string | null>(null)
  const [editingRow, setEditingRow]               = useState<StagingRow | null>(null)
  const [editAh, setEditAh]                       = useState<string>('')
  const [editTech, setEditTech]                   = useState<string>('')
  const [editSaving, setEditSaving]               = useState(false)
  const [editError, setEditError]                 = useState<string | null>(null)
  const [commitModalOpen, setCommitModalOpen]     = useState(false)
  const [commitLoading, setCommitLoading]         = useState(false)
  const [commitResult, setCommitResult]           = useState<CommitStagingResult | null>(null)
  const [discardLoading, setDiscardLoading]       = useState(false)
  const [conflictResolutions, setConflictResolutions] = useState<Record<string, 'staging' | 'current'>>({})
  const [preCommitConflicts, setPreCommitConflicts] = useState<{ make_n: string; model_n: string; year: number; conflict_detail: { current: { ah: number|null; technology: string|null; source: string }; staged: { ah: number|null; technology: string|null; source: string } } }[]>([])

  // Version history state
  const [showVersions, setShowVersions]           = useState(false)
  const [versions, setVersions]                   = useState<ValidationVersion[]>([])
  const [versionsTotal, setVersionsTotal]         = useState(0)
  const [versionsPage, setVersionsPage]           = useState(1)
  const [versionsLoading, setVersionsLoading]     = useState(false)
  const [openChangelog, setOpenChangelog]         = useState<VersionChangelogResponse | null>(null)
  const [changelogLoading, setChangelogLoading]   = useState(false)
  const [revertingId, setRevertingId]             = useState<string | null>(null)
  const [revertResult, setRevertResult]           = useState<RevertVersionResult | null>(null)

  // Staleness state
  const [staleness, setStaleness]                 = useState<StalenessInfo | null>(null)

  // Nav blocker — warn when staging has uncommitted data
  const [showNavWarning, setShowNavWarning] = useState(false)
  const pendingNavRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    if (!stagingInfo?.has_staging) return
    const handler = (e: BeforeUnloadEvent) => { e.preventDefault() }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [stagingInfo?.has_staging])

  const blocker = {
    state: showNavWarning ? 'blocked' : 'idle',
    reset: () => { setShowNavWarning(false); pendingNavRef.current = null },
    proceed: () => { const fn = pendingNavRef.current; setShowNavWarning(false); pendingNavRef.current = null; fn?.() },
  }

  const fetchStagingArea = useCallback(async (filter: 'all' | 'valid' | 'invalid' | 'conflicts' = 'all', page = 1) => {
    setStagingLoading(true)
    try {
      const s = await getStagingArea(page, 50, filter)
      setStagingInfo(s)
    } catch { /* ignore */ } finally {
      setStagingLoading(false)
    }
  }, [])

  async function handleSaveEdit() {
    if (!editingRow) return
    setEditSaving(true)
    setEditError(null)
    try {
      const updated = await patchStagingRow(editingRow.id, {
        ah:         editAh.trim() === '' ? null : Number(editAh),
        technology: editTech.trim() === '' ? null : editTech.trim(),
      })
      setStagingInfo(prev => {
        if (!prev) return prev
        return {
          ...prev,
          items: prev.items.map(r => r.id === updated.id ? updated : r),
        }
      })
      setEditingRow(null)
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setEditSaving(false)
    }
  }

  async function fetchAll() {
    try {
      const [s, q, c, p, stale, staging] = await Promise.all([
        getWebValidateStatus(),
        getPipelineQuotas(),
        getWebValidateCoverage(),
        getWebValidateProviders(),
        getPipelineStaleness().catch(() => null),
        getStagingArea(1, 50, 'all').catch(() => null),
      ])
      setStatus(s)
      setQuotas(q)
      setCoverage(c)
      setProviderInfo(p)
      if (stale) setStaleness(stale)
      if (staging) setStagingInfo(staging)
      // Initialise enabled providers: always-on + any configured limited providers
      setEnabledProviders(new Set(
        p.filter(pi => pi.always_available || pi.configured).map(pi => pi.provider)
      ))
    } catch {
      // leave existing state intact on transient errors
    } finally {
      setTabLoading(false)
    }
  }

  async function fetchVersions(page = 1) {
    setVersionsLoading(true)
    try {
      const r = await getValidationVersions(page, 20)
      setVersions(r.items)
      setVersionsTotal(r.total)
      setVersionsPage(page)
    } catch { /* ignore */ } finally {
      setVersionsLoading(false)
    }
  }

  async function handleOpenChangelog(versionId: string) {
    setChangelogLoading(true)
    try {
      const r = await getVersionChangelog(versionId)
      setOpenChangelog(r)
    } catch { /* ignore */ } finally {
      setChangelogLoading(false)
    }
  }

  async function handleRevert(v: ValidationVersion) {
    if (!window.confirm(
      `Revert version #${v.version_number}?\n\n` +
      `This will undo ${v.committed_count} added and ${v.removed_count} removed rows, ` +
      `and create a new version record.\n\nThis cannot be undone.`
    )) return
    setRevertingId(v.id)
    setActionError(null)
    try {
      const r = await revertVersion(v.id)
      setRevertResult(r)
      fetchVersions(1)
      const [c, stale] = await Promise.all([
        getWebValidateCoverage().catch(() => null),
        getPipelineStaleness().catch(() => null),
      ])
      if (c) setCoverage(c)
      if (stale) setStaleness(stale)
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setRevertingId(null)
    }
  }

  useEffect(() => {
    fetchAll()
    return () => { if (pollingRef.current) clearInterval(pollingRef.current) }
  }, [])

  useEffect(() => {
    if (showVersions) fetchVersions(1)
  }, [showVersions])

  useEffect(() => {
    if (!showMatched) return
    setMatchedLoading(true)
    getWebValidateMatched(matchedPage, 50, matchedSearch)
      .then(d => setMatchedData(d))
      .catch(() => {})
      .finally(() => setMatchedLoading(false))
  }, [showMatched, matchedPage])

  function handleMatchedSearchChange(val: string) {
    setMatchedSearch(val)
    setMatchedPage(1)
    if (matchedDebounceRef.current) clearTimeout(matchedDebounceRef.current)
    matchedDebounceRef.current = setTimeout(() => {
      setMatchedLoading(true)
      getWebValidateMatched(1, 50, val)
        .then(d => setMatchedData(d))
        .catch(() => {})
        .finally(() => setMatchedLoading(false))
    }, 300)
  }

  useEffect(() => {
    const active = status?.status === 'running' || status?.status === 'paused'
    if (active) {
      pollingRef.current = setInterval(async () => {
        try {
          const s = await getWebValidateStatus()
          setStatus(s)
          if (s.status !== 'running' && s.status !== 'paused') {
            clearInterval(pollingRef.current!)
            pollingRef.current = null
            setIsStopping(false)
            const [q, c, stale] = await Promise.all([
              getPipelineQuotas(),
              getWebValidateCoverage(),
              getPipelineStaleness().catch(() => null),
            ])
            setQuotas(q)
            setCoverage(c)
            if (stale) setStaleness(stale)
          }
        } catch { /* ignore transient */ }
      }, 1000)
    } else {
      if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null }
    }
    return () => { if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null } }
  }, [status?.status])

  async function handleRun() {
    setActionError(null)
    setLoadingRun(true)
    try {
      await runWebValidatePipeline([...enabledProviders])
      const s = await getWebValidateStatus()
      setStatus(s)
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoadingRun(false)
    }
  }

  async function handlePause() {
    setActionError(null)
    setActionInProgress('pause')
    try {
      await pauseWebValidate()
      setStatus(s => s ? { ...s, status: 'paused' } : s)
      const s = await getWebValidateStatus()
      setStatus(s)
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setActionInProgress(null)
    }
  }

  async function handleResume() {
    setActionError(null)
    setActionInProgress('resume')
    try {
      await resumeWebValidate()
      setStatus(s => s ? { ...s, status: 'running' } : s)
      const s = await getWebValidateStatus()
      setStatus(s)
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setActionInProgress(null)
    }
  }

  async function handleCancel() {
    setIsStopping(true)
    setActionError(null)
    setActionInProgress('cancel')
    try {
      const result = await cancelWebValidate()
      const s = await getWebValidateStatus()
      setStatus(s)
      if (result.staged_count > 0) {
        const warnParts: string[] = []
        if (result.invalid_count > 0) warnParts.push(`${result.invalid_count} data warning${result.invalid_count > 1 ? 's' : ''}`)
        if (result.conflict_count > 0) warnParts.push(`${result.conflict_count} conflict${result.conflict_count > 1 ? 's' : ''}`)
        const warnStr = warnParts.length > 0 ? ` — ${warnParts.join(', ')}` : ''
        setStagingToast(`${result.staged_count} matched vehicle${result.staged_count > 1 ? 's' : ''} saved to staging area for validation${warnStr}.`)
        await fetchStagingArea('all', 1)
        const c = await getWebValidateCoverage().catch(() => null)
        if (c) setCoverage(c)
      }
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setActionInProgress(null)
    }
  }

  async function handleStagingFilterChange(filter: 'all' | 'valid' | 'invalid' | 'conflicts') {
    setStagingFilter(filter)
    setStagingPage(1)
    await fetchStagingArea(filter, 1)
  }

  async function handleStagingPageChange(page: number) {
    setStagingPage(page)
    await fetchStagingArea(stagingFilter, page)
  }

  async function handleOpenCommitModal() {
    setCommitResult(null)
    setConflictResolutions({})
    const preCommit = await getStagingPreCommit().catch(() => ({ conflict_count: 0, conflicts: [] }))
    setPreCommitConflicts(preCommit.conflicts)
    setCommitModalOpen(true)
  }

  async function handleCommit() {
    setCommitLoading(true)
    try {
      const resolutions: ConflictResolution[] = preCommitConflicts.map(c => {
        const key = `${c.make_n}|${c.model_n}|${c.year}`
        return { make_n: c.make_n, model_n: c.model_n, year: c.year, keep: conflictResolutions[key] ?? 'staging' }
      })
      const result = await commitStagingArea(resolutions)
      setCommitResult(result)
      setStagingInfo(null)
      setStagingToast(null)
      // Refresh coverage and matched
      const [c, stale] = await Promise.all([getWebValidateCoverage(), getPipelineStaleness().catch(() => null)])
      setCoverage(c)
      if (stale) setStaleness(stale)
      if (showMatched) {
        const md = await getWebValidateMatched(1, 50, matchedSearch).catch(() => null)
        if (md) { setMatchedData(md); setMatchedPage(1) }
      }
      if (showVersions) fetchVersions(1)
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setCommitLoading(false)
    }
  }

  async function handleDiscard() {
    setDiscardLoading(true)
    try {
      await discardStagingArea()
      setStagingInfo(null)
      setStagingToast(null)
      const c = await getWebValidateCoverage().catch(() => null)
      if (c) setCoverage(c)
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setDiscardLoading(false)
    }
  }

  async function handleRefreshQuotas() {
    setLoadingQuotas(true)
    try {
      const q = await getPipelineQuotas()
      setQuotas(q)
    } catch { /* ignore */ } finally {
      setLoadingQuotas(false)
    }
  }

  async function handleCacheReset() {
    setCacheResetMsg(null)
    setLoadingCacheReset(true)
    // Optimistically zero out matched count immediately
    setCoverage(c => c ? { ...c, matched: 0, unmatched: c.total, pct_matched: 0, unmatched_vehicles: [] } : null)
    setMatchedData(null)
    setShowMatched(false)
    try {
      const res = await resetWebValidateCache()
      const rowsMsg = res.rows_cleared > 0 ? ` — ${res.rows_cleared.toLocaleString()} matched vehicle rows removed.` : ''
      setCacheResetMsg(res.deleted ? `Cache cleared${rowsMsg}` : `No cache file found${rowsMsg}`)
      setCoverageLoading(true)
      const c = await getWebValidateCoverage()
      setCoverage(c)
    } catch (e: unknown) {
      setCacheResetMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setLoadingCacheReset(false)
      setCoverageLoading(false)
      setTimeout(() => setCacheResetMsg(null), 7000)
    }
  }

  const isRunning = status?.status === 'running'
  const isPaused  = status?.status === 'paused'
  const isPhase1 = (status?.processed ?? 0) === 0 && (status?.phase1_total ?? 0) > 0
  const progressPct = isPhase1
    ? Math.round(((status?.phase1_processed ?? 0) / status!.phase1_total) * 100)
    : (status?.total ?? 0) > 0
      ? Math.round((status!.processed / status!.total) * 100)
      : 0

  const etaSeconds = (() => {
    // Use phase2_started_at so Phase 1 web-prefetch time doesn't skew the rate
    const ref = (status as any)?.phase2_started_at ?? status?.started_at
    if (!ref || !status?.processed || !status.total) return NaN
    const elapsedSec = (Date.now() - new Date(ref).getTime()) / 1000
    if (elapsedSec < 1) return NaN
    const rate = status.processed / elapsedSec
    return (status.total - status.processed) / rate
  })()

  const limitedProviders = quotas.filter(q => q.quota_limit !== -1)
  const anyAtWarning     = limitedProviders.some(q => q.pct_used >= 80)
  const allLimitedOut    = limitedProviders.length > 0 && limitedProviders.every(q => q.calls_made >= q.quota_limit)

  // Filtered + paginated unmatched list (client-side)
  const allUnmatched     = coverage?.unmatched_vehicles ?? []
  const filteredUnmatched = coverageSearch
    ? allUnmatched.filter(v =>
        v.make_n.includes(coverageSearch.toUpperCase()) ||
        v.model_n.includes(coverageSearch.toUpperCase())
      )
    : allUnmatched
  const totalPages  = Math.max(1, Math.ceil(filteredUnmatched.length / COVERAGE_PAGE_SIZE))
  const pagedRows   = filteredUnmatched.slice((coveragePage - 1) * COVERAGE_PAGE_SIZE, coveragePage * COVERAGE_PAGE_SIZE)

  function handleSearchChange(val: string) {
    setCoverageSearch(val)
    setCoveragePage(1)
  }

  const matchedPct    = coverage?.pct_matched ?? 0
  const matchedCount  = coverage?.matched ?? 0
  const totalCount    = coverage?.total ?? 0
  const unmatchedCount = coverage?.unmatched ?? 0

  if (tabLoading) return <WebValidateLoadingOverlay />

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

      {/* Staleness banner */}
      {staleness?.stale && (
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.6rem', background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: 10, padding: '0.75rem 1rem' }}>
          <ClockIcon style={{ width: 16, height: 16, color: '#f59e0b', flexShrink: 0, marginTop: 1 }} />
          <p style={{ margin: 0, fontSize: '0.75rem', color: '#92400e', lineHeight: 1.6 }}>
            <strong>Vehicle data has changed since the last pipeline run.</strong>
            {staleness.new_vehicles_since_last_run > 0 && ` ${staleness.new_vehicles_since_last_run.toLocaleString()} new vehicle combinations need validation.`}
            {' '}Run the pipeline to update matches.
          </p>
        </div>
      )}

      {/* Staging toast */}
      {stagingToast && (
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.6rem', background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: 10, padding: '0.75rem 1rem' }}>
          <ArchiveBoxIcon style={{ width: 16, height: 16, color: '#f59e0b', flexShrink: 0, marginTop: 1 }} />
          <p style={{ margin: 0, fontSize: '0.75rem', color: '#92400e', lineHeight: 1.6, flex: 1 }}>
            <strong>Staging area updated.</strong> {stagingToast} Review below before committing to master.
          </p>
          <button onClick={() => setStagingToast(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 2, color: '#92400e' }}>
            <XMarkIcon style={{ width: 14, height: 14 }} />
          </button>
        </div>
      )}

      {/* Revert success banner */}
      {revertResult && (
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.6rem', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 10, padding: '0.75rem 1rem' }}>
          <CheckCircleIcon style={{ width: 16, height: 16, color: '#22c55e', flexShrink: 0, marginTop: 1 }} />
          <p style={{ margin: 0, fontSize: '0.75rem', color: '#14532d', lineHeight: 1.6, flex: 1 }}>
            <strong>Reverted version #{revertResult.reverted_version_number}.</strong>{' '}
            {revertResult.changes} row{revertResult.changes !== 1 ? 's' : ''} restored — saved as version #{revertResult.version_number}.
          </p>
          <button onClick={() => setRevertResult(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 2, color: '#14532d' }}>
            <XMarkIcon style={{ width: 14, height: 14 }} />
          </button>
        </div>
      )}

      {/* Commit success banner */}
      {commitResult && !commitModalOpen && (
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.6rem', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 10, padding: '0.75rem 1rem' }}>
          <CheckCircleIcon style={{ width: 16, height: 16, color: '#22c55e', flexShrink: 0, marginTop: 1 }} />
          <p style={{ margin: 0, fontSize: '0.75rem', color: '#14532d', lineHeight: 1.6, flex: 1 }}>
            <strong>Committed as version #{commitResult.version_number}.</strong>{' '}
            {commitResult.committed} records committed, {commitResult.removed_invalid} invalid records removed
            {commitResult.conflicts_resolved > 0 ? `, ${commitResult.conflicts_resolved} conflicts resolved` : ''}.
          </p>
          <button onClick={() => setCommitResult(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 2, color: '#14532d' }}>
            <XMarkIcon style={{ width: 14, height: 14 }} />
          </button>
        </div>
      )}

      {/* Info banner */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.6rem', background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 10, padding: '0.75rem 1rem' }}>
        <InformationCircleIcon style={{ width: 16, height: 16, color: '#3b82f6', flexShrink: 0, marginTop: 1 }} />
        <p style={{ margin: 0, fontSize: '0.75rem', color: '#1d4ed8', lineHeight: 1.6 }}>
          Looks up internet-accepted battery specs for each vehicle in the database. Phase 1 searches per 5-year generation bucket; provider chain: <strong>DuckDuckGo</strong> → <strong>Google CSE</strong> → <strong>Tavily</strong>. Results are saved to <code>web_battery_validation</code>. DuckDuckGo is always available (unlimited); Google CSE and Tavily have monthly quotas.
        </p>
      </div>

      {/* Provider Selection — only shown when idle */}
      {!isRunning && !isPaused && (
        <div style={{ ...CARD, padding: '1.25rem 1.5rem' }}>
          <h3 style={{ margin: '0 0 1rem', fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.8)' }}>
            Providers for this run
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.65rem' }}>
            {(['duckduckgo', 'google_cse', 'tavily'] as const).map(p => {
              const info             = providerInfo.find(pi => pi.provider === p)
              const isAlways         = info?.always_available ?? (p === 'duckduckgo')
              const isConfigured     = info?.configured ?? false
              const isOn             = enabledProviders.has(p)
              const noKey            = !isAlways && !isConfigured
              const quota            = quotas.find(q => q.provider === p)
              const isQuotaExhausted = !isAlways && !!quota && quota.quota_limit !== -1 && quota.calls_made >= quota.quota_limit
              const isQuotaWarning   = !isAlways && !!quota && quota.quota_limit !== -1 && quota.pct_used >= 80 && !isQuotaExhausted
              const isUnavailable    = noKey || isQuotaExhausted
              const canToggle        = !isAlways && isConfigured && !isQuotaExhausted

              const bg    = isUnavailable ? '#f9fafb' : isOn ? '#f0fdf4' : '#fff5f5'
              const border = isUnavailable ? '#e2e4e9' : isOn ? '#bbf7d0' : '#fecaca'

              return (
                <div key={p} style={{
                  display: 'flex', alignItems: 'center', gap: '0.65rem',
                  background: bg, border: `1px solid ${border}`,
                  borderRadius: 10, padding: '0.65rem 0.85rem',
                  opacity: isUnavailable ? 0.55 : 1,
                }}>
                  <GlobeAltIcon style={{ width: 13, height: 13, color: isUnavailable ? '#9ca3af' : '#6b7280', flexShrink: 0 }} />
                  <span style={{ fontSize: '0.78rem', fontWeight: 600, color: isUnavailable ? '#9ca3af' : 'rgba(17,24,39,0.8)', flex: 1 }}>
                    {PROVIDER_LABELS[p] ?? p}
                  </span>

                  {isAlways && (
                    <span style={{ fontSize: '0.62rem', fontWeight: 700, color: '#16a34a', background: '#dcfce7', borderRadius: 99, padding: '0.1rem 0.45rem', whiteSpace: 'nowrap' }}>
                      Always on
                    </span>
                  )}

                  {isQuotaWarning && (
                    <span style={{ fontSize: '0.62rem', fontWeight: 600, color: '#92400e', background: '#fef3c7', borderRadius: 99, padding: '0.1rem 0.45rem', whiteSpace: 'nowrap' }}>
                      {quota!.pct_used}% used
                    </span>
                  )}

                  {canToggle && (
                    <button
                      onClick={() => setEnabledProviders(prev => {
                        const next = new Set(prev)
                        if (next.has(p)) next.delete(p); else next.add(p)
                        return next
                      })}
                      title={isOn ? 'Click to disable for this run' : 'Click to enable for this run'}
                      style={{
                        position: 'relative', width: 36, height: 20,
                        borderRadius: 99, border: 'none', cursor: 'pointer', padding: 0, flexShrink: 0,
                        background: isOn ? '#22c55e' : '#d1d5db', transition: 'background 0.18s',
                      }}
                    >
                      <span style={{
                        position: 'absolute', top: 2, left: isOn ? 18 : 2,
                        width: 16, height: 16, borderRadius: '50%', background: '#fff',
                        transition: 'left 0.18s', boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                      }} />
                    </button>
                  )}

                  {noKey && (
                    <span style={{ fontSize: '0.62rem', fontWeight: 600, color: '#9ca3af', whiteSpace: 'nowrap' }}>No API key</span>
                  )}
                  {isQuotaExhausted && (
                    <span style={{ fontSize: '0.62rem', fontWeight: 600, color: R, whiteSpace: 'nowrap' }}>Quota exhausted</span>
                  )}
                </div>
              )
            })}
          </div>

          {providerInfo.some(p => !p.always_available && !p.configured) && (
            <p style={{ margin: '0.85rem 0 0', fontSize: '0.7rem', color: '#9ca3af', lineHeight: 1.6 }}>
              Contact IT if default providers do not activate or for disabled providers.
            </p>
          )}
        </div>
      )}

      {/* Patience banner — shown after Stop is clicked while pipeline is still running */}
      {isStopping && isRunning && (
        <div style={{
          background: '#fef3c7', border: '1px solid #f59e0b', borderRadius: 8,
          padding: '0.6rem 1rem', fontSize: '0.75rem', color: '#92400e',
          display: 'flex', alignItems: 'center', gap: '0.5rem',
          marginBottom: '0.5rem',
        }}>
          <span>⚠</span>
          <span>Stopping… please wait for the pipeline to finish before closing this page — leaving early may corrupt the cache.</span>
        </div>
      )}

      {/* Run / Pause / Resume / Stop controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', flexWrap: 'wrap' }}>
        {!isRunning && !isPaused ? (
          /* ── Idle state: Run button ── */
          <button
            onClick={handleRun}
            disabled={loadingRun}
            style={{
              display: 'flex', alignItems: 'center', gap: '0.45rem',
              fontSize: '0.82rem', fontWeight: 700,
              padding: '0.65rem 1.35rem', borderRadius: 10, border: 'none',
              cursor: loadingRun ? 'not-allowed' : 'pointer',
              background: loadingRun ? '#e2e4e9' : R,
              color: loadingRun ? 'rgba(107,114,128,0.7)' : '#fff',
              transition: 'background 0.15s',
            }}
            onMouseEnter={e => { if (!loadingRun) e.currentTarget.style.background = RD }}
            onMouseLeave={e => { if (!loadingRun) e.currentTarget.style.background = R }}
          >
            <PlayIcon style={{ width: 14, height: 14 }} />
            {loadingRun ? 'Starting…' : 'Run Web Validate'}
          </button>
        ) : isPaused ? (
          /* ── Paused state: Resume + Stop ── */
          <>
            <button
              onClick={handleResume}
              disabled={!!actionInProgress}
              style={{
                display: 'flex', alignItems: 'center', gap: '0.45rem',
                fontSize: '0.82rem', fontWeight: 700,
                padding: '0.65rem 1.35rem', borderRadius: 10, border: 'none',
                cursor: actionInProgress ? 'not-allowed' : 'pointer',
                background: actionInProgress ? '#e2e4e9' : '#22c55e',
                color: actionInProgress ? 'rgba(107,114,128,0.7)' : '#fff',
                transition: 'background 0.15s', opacity: actionInProgress && actionInProgress !== 'resume' ? 0.5 : 1,
              }}
              onMouseEnter={e => { if (!actionInProgress) e.currentTarget.style.background = '#16a34a' }}
              onMouseLeave={e => { if (!actionInProgress) e.currentTarget.style.background = '#22c55e' }}
            >
              {actionInProgress === 'resume' ? <ArrowSpinner /> : <PlayIcon style={{ width: 14, height: 14 }} />}
              {actionInProgress === 'resume' ? 'Resuming…' : 'Resume'}
            </button>
            <button
              onClick={handleCancel}
              disabled={!!actionInProgress}
              style={{
                display: 'flex', alignItems: 'center', gap: '0.45rem',
                fontSize: '0.82rem', fontWeight: 700,
                padding: '0.65rem 1.35rem', borderRadius: 10, border: 'none',
                cursor: actionInProgress ? 'not-allowed' : 'pointer',
                background: actionInProgress === 'cancel' ? '#7f1d1d' : actionInProgress ? '#e2e4e9' : R,
                color: actionInProgress && actionInProgress !== 'cancel' ? 'rgba(107,114,128,0.7)' : '#fff',
                transition: 'background 0.15s', opacity: actionInProgress && actionInProgress !== 'cancel' ? 0.5 : 1,
              }}
              onMouseEnter={e => { if (!actionInProgress) e.currentTarget.style.background = RD }}
              onMouseLeave={e => { if (!actionInProgress) e.currentTarget.style.background = R }}
            >
              {actionInProgress === 'cancel' ? <ArrowSpinner /> : <StopIcon style={{ width: 14, height: 14 }} />}
              {actionInProgress === 'cancel' ? 'Stopping…' : 'Stop'}
            </button>
          </>
        ) : (
          /* ── Running state: Pause + Stop ── */
          <>
            <button
              onClick={handlePause}
              disabled={!!actionInProgress}
              style={{
                display: 'flex', alignItems: 'center', gap: '0.45rem',
                fontSize: '0.82rem', fontWeight: 700,
                padding: '0.65rem 1.35rem', borderRadius: 10, border: 'none',
                cursor: actionInProgress ? 'not-allowed' : 'pointer',
                background: actionInProgress === 'pause' ? '#d97706' : actionInProgress ? '#e2e4e9' : '#f59e0b',
                color: actionInProgress && actionInProgress !== 'pause' ? 'rgba(107,114,128,0.7)' : '#fff',
                transition: 'background 0.15s', opacity: actionInProgress && actionInProgress !== 'pause' ? 0.5 : 1,
              }}
              onMouseEnter={e => { if (!actionInProgress) e.currentTarget.style.background = '#d97706' }}
              onMouseLeave={e => { if (!actionInProgress) e.currentTarget.style.background = '#f59e0b' }}
            >
              {actionInProgress === 'pause' ? <ArrowSpinner /> : <PauseIcon style={{ width: 14, height: 14 }} />}
              {actionInProgress === 'pause' ? 'Pausing…' : 'Pause'}
            </button>
            <button
              onClick={handleCancel}
              disabled={!!actionInProgress}
              style={{
                display: 'flex', alignItems: 'center', gap: '0.45rem',
                fontSize: '0.82rem', fontWeight: 700,
                padding: '0.65rem 1.35rem', borderRadius: 10, border: 'none',
                cursor: actionInProgress ? 'not-allowed' : 'pointer',
                background: actionInProgress === 'cancel' ? '#7f1d1d' : actionInProgress ? '#e2e4e9' : R,
                color: actionInProgress && actionInProgress !== 'cancel' ? 'rgba(107,114,128,0.7)' : '#fff',
                transition: 'background 0.15s', opacity: actionInProgress && actionInProgress !== 'cancel' ? 0.5 : 1,
              }}
              onMouseEnter={e => { if (!actionInProgress) e.currentTarget.style.background = RD }}
              onMouseLeave={e => { if (!actionInProgress) e.currentTarget.style.background = R }}
            >
              {actionInProgress === 'cancel' ? <ArrowSpinner /> : <StopIcon style={{ width: 14, height: 14 }} />}
              {actionInProgress === 'cancel' ? 'Stopping…' : 'Stop'}
            </button>
          </>
        )}
        {actionError && (
          <span style={{ fontSize: '0.75rem', color: R }}>{actionError}</span>
        )}

        {/* Clear Cache — pushed to the right */}
        <button
          onClick={handleCacheReset}
          disabled={isRunning || isPaused || loadingCacheReset}
          title="Delete the local lookup cache so the next run re-fetches all vehicles"
          style={{
            display: 'flex', alignItems: 'center', gap: '0.4rem',
            fontSize: '0.75rem', fontWeight: 600,
            padding: '0.55rem 1rem', borderRadius: 10,
            border: '1px solid #e2e4e9', cursor: (isRunning || isPaused || loadingCacheReset) ? 'not-allowed' : 'pointer',
            background: '#fff', color: 'rgba(107,114,128,0.8)',
            opacity: (isRunning || isPaused || loadingCacheReset) ? 0.5 : 1,
            marginLeft: 'auto', whiteSpace: 'nowrap', transition: 'all 0.15s',
          }}
        >
          <ArrowPathIcon style={{ width: 13, height: 13 }} />
          {loadingCacheReset ? 'Clearing…' : 'Clear Cache'}
        </button>
        {cacheResetMsg && (
          <span style={{ fontSize: '0.72rem', color: '#6b7280' }}>{cacheResetMsg}</span>
        )}
      </div>

      {/* Last run summary */}
      {status && (status.status === 'done' || status.status === 'cancelled' || status.status === 'error') && (
        <div style={{ ...CARD, padding: '1rem 1.25rem', borderLeft: `4px solid ${status.status === 'error' ? R : status.status === 'cancelled' ? '#f59e0b' : '#22c55e'}` }}>
          <div style={{ fontSize: '0.7rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', color: 'rgba(107,114,128,0.7)', marginBottom: '0.75rem' }}>
            Last Run {status.finished_at ? `— ${new Date(status.finished_at).toLocaleString()}` : ''}
          </div>
          {status.status === 'error' && status.error_detail && (
            <p style={{ margin: '0 0 0.75rem', fontSize: '0.75rem', color: R }}>{status.error_detail}</p>
          )}
          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
            <SummaryBadge label="Found"     value={status.found}     color="#22c55e" />
            <SummaryBadge label="Not Found" value={status.not_found} color="#9ca3af" />
            <SummaryBadge label="Total"     value={status.total} />
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {Object.entries(status.provider_counts).filter(([, n]) => n > 0).map(([p, n]) => (
              <span key={p} style={{ fontSize: '0.7rem', background: '#f4f5f7', borderRadius: 99, padding: '0.2rem 0.6rem', color: 'rgba(17,24,39,0.7)', fontWeight: 600 }}>
                {PROVIDER_LABELS[p] ?? p}: {n}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Live progress */}
      {(isRunning || isPaused) && (
        <div style={{ ...CARD, padding: '1rem 1.25rem', borderLeft: `4px solid ${isPaused ? '#f59e0b' : '#3b82f6'}` }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.6rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              {isPaused
                ? <PauseIcon style={{ width: 16, height: 16, color: '#f59e0b' }} />
                : <ArrowSpinner />
              }
              <span style={{ fontSize: '0.8rem', fontWeight: 700, color: isPaused ? '#92400e' : '#1d4ed8' }}>
                {isPaused ? 'Paused' : (status?.processed === 0 ? 'Pre-fetching web data…' : 'Running…')}
              </span>
              {!isPaused && status?.processed === 0 && (
                <span style={{ fontSize: '0.72rem', background: '#faf5ff', border: '1px solid #e9d5ff', borderRadius: 99, padding: '0.15rem 0.55rem', color: '#7c3aed' }}>
                  Phase 1 of 2
                </span>
              )}
              {!isPaused && status?.processed !== 0 && status?.current_provider && status.current_provider !== 'none' && (
                <span style={{ fontSize: '0.72rem', background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 99, padding: '0.15rem 0.55rem', color: '#1d4ed8' }}>
                  via {PROVIDER_LABELS[status.current_provider] ?? status.current_provider}
                </span>
              )}
              {!isPaused && status?.processed === 0 && (status?.phase1_total ?? 0) > 0 && (
                <span style={{ fontSize: '0.72rem', color: '#6b7280' }}>
                  {status!.phase1_processed} / {status!.phase1_total} buckets
                </span>
              )}
              {!isPaused && (status?.processed ?? 0) > 0 && status?.current_combo && (
                <span style={{ fontSize: '0.7rem', color: '#6b7280', fontFamily: 'monospace' }}>
                  ↳ {status.current_combo}
                </span>
              )}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.1rem' }}>
              {(status?.processed ?? 0) === 0 ? (
                <>
                  <span style={{ fontSize: '0.75rem', fontWeight: 700, color: 'rgba(17,24,39,0.7)' }}>
                    {(status?.phase1_total ?? 0) > 0
                      ? `${Math.round(((status?.phase1_processed ?? 0) / status!.phase1_total) * 100)}%`
                      : '—'}
                  </span>
                  {isRunning && status?.started_at && (
                    <Phase1ElapsedTimer startedAt={status.started_at} />
                  )}
                </>
              ) : (
                <>
                  <span style={{ fontSize: '0.75rem', fontWeight: 700, color: 'rgba(17,24,39,0.7)' }}>
                    {status?.processed ?? 0} / {status?.total ?? '?'}
                    {(status?.total ?? 0) > 0 && (
                      <span style={{ marginLeft: 6, fontSize: '0.7rem', fontWeight: 600, color: '#6b7280' }}>
                        ({progressPct}%)
                      </span>
                    )}
                  </span>
                  {isRunning && (
                    <span style={{ fontSize: '0.65rem', color: '#6b7280' }}>
                      {formatEta(etaSeconds)}
                    </span>
                  )}
                </>
              )}
            </div>
          </div>
          <div style={{ background: '#e2e4e9', borderRadius: 99, height: 8, overflow: 'hidden' }}>
            <div style={{
              width: `${progressPct}%`,
              background: getProgressBarColor(progressPct, isPaused),
              height: '100%', borderRadius: 99, transition: 'width 0.5s',
            }} />
          </div>
          {status && Object.values(status.provider_counts).some(n => n > 0) && (
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.6rem' }}>
              {Object.entries(status.provider_counts).filter(([, n]) => n > 0).map(([p, n]) => (
                <span key={p} style={{ fontSize: '0.7rem', background: '#f4f5f7', borderRadius: 99, padding: '0.2rem 0.6rem', color: 'rgba(17,24,39,0.7)', fontWeight: 600 }}>
                  {PROVIDER_LABELS[p] ?? p}: {n}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Log panel */}
      {(isRunning || isPaused || (status?.logs && status.logs.length > 0)) && (
        <LogPanel lines={status?.logs ?? []} />
      )}

      {/* Coverage Summary */}
      <div style={{ ...CARD, padding: '1.25rem 1.5rem', opacity: coverageLoading ? 0.5 : 1, transition: 'opacity 0.3s' }}>
        <h3 style={{ margin: '0 0 1rem', fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.8)' }}>
          Battery Coverage
        </h3>
        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
          <SummaryBadge label="Total Combos"      value={totalCount.toLocaleString()} />
          <SummaryBadge label="Matched"           value={matchedCount.toLocaleString()} color="#22c55e" />
          <SummaryBadge label="Unmatched"         value={unmatchedCount.toLocaleString()} color={unmatchedCount > 0 ? R : '#22c55e'} />
          <SummaryBadge label="Committed to Master" value={(coverage?.master_count ?? 0).toLocaleString()} color="#22c55e" />
          {(coverage?.staging_count ?? 0) > 0 && (
            <SummaryBadge label="In Staging" value={(coverage?.staging_count ?? 0).toLocaleString()} color="#f59e0b" />
          )}
        </div>
        {/* Segmented progress bar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div style={{ flex: 1, background: '#e2e4e9', borderRadius: 99, height: 10, overflow: 'hidden' }}>
            <div style={{
              width: `${matchedPct}%`, background: '#22c55e',
              height: '100%', borderRadius: 99, transition: 'width 0.5s',
            }} />
          </div>
          <span style={{ fontSize: '0.75rem', fontWeight: 800, color: '#22c55e', whiteSpace: 'nowrap' }}>
            {matchedPct.toFixed(1)}% covered
          </span>
        </div>
      </div>

      {/* Staging Area Panel */}
      {stagingInfo?.has_staging && (
        <div style={{ ...CARD, padding: '1.25rem 1.5rem', border: '1px solid #fcd34d', background: '#fffdf0' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.5rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <ArchiveBoxIcon style={{ width: 15, height: 15, color: '#f59e0b' }} />
              <h3 style={{ margin: 0, fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: '#92400e' }}>
                Staging Area — Review &amp; Resolve Before Committing
              </h3>
            </div>
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              {/* Summary chips */}
              {[
                { label: 'Total', val: stagingInfo.total, color: '#374151' },
                { label: 'Valid', val: stagingInfo.valid_count, color: '#22c55e' },
                { label: 'Invalid', val: stagingInfo.invalid_count, color: R },
                { label: 'Conflicts', val: stagingInfo.conflict_count, color: '#f59e0b' },
              ].map(({ label, val, color }) => val > 0 && (
                <span key={label} style={{ fontSize: '0.7rem', fontWeight: 700, background: '#fff', border: '1px solid #e2e4e9', borderRadius: 99, padding: '0.2rem 0.6rem', color }}>
                  {val} {label}
                </span>
              ))}
            </div>
          </div>

          {/* Filter tabs */}
          <div style={{ display: 'flex', gap: '0.35rem', marginBottom: '0.75rem' }}>
            {(['all', 'valid', 'invalid', 'conflicts'] as const).map(f => (
              <button
                key={f}
                onClick={() => handleStagingFilterChange(f)}
                style={{
                  fontSize: '0.72rem', fontWeight: stagingFilter === f ? 700 : 500,
                  padding: '0.3rem 0.65rem', borderRadius: 8, border: 'none', cursor: 'pointer',
                  background: stagingFilter === f ? '#f59e0b' : '#f4f5f7',
                  color: stagingFilter === f ? '#fff' : '#6b7280',
                  transition: 'all 0.15s',
                }}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>

          {/* Staging table */}
          {stagingLoading ? (
            <p style={{ margin: '0.5rem 0', fontSize: '0.75rem', color: '#9ca3af' }}>Loading…</p>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.74rem' }}>
                <thead>
                  <tr style={{ background: '#fef3c7' }}>
                    {['Make', 'Model', 'Year', 'Ah', 'Tech', 'Source', 'Status', ''].map(col => (
                      <th key={col} style={{ padding: '0.5rem 0.75rem', textAlign: 'left', fontWeight: 700, color: '#92400e', fontSize: '0.65rem', textTransform: 'uppercase', letterSpacing: '0.07em', whiteSpace: 'nowrap' }}>
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(stagingInfo.items?.length ?? 0) === 0 ? (
                    <tr><td colSpan={7} style={{ padding: '1rem', textAlign: 'center', color: '#9ca3af' }}>No records in this filter</td></tr>
                  ) : stagingInfo.items.map((row: StagingRow, i: number) => (
                    <>
                      <tr key={`${row.make_n}-${row.model_n}-${row.year}`}
                        style={{
                          background: !row.is_valid ? '#fff5f5' : row.conflict ? '#fffbeb' : i % 2 === 0 ? '#fff' : '#fffdf5',
                          borderBottom: '1px solid #fcd34d',
                        }}
                      >
                        <td style={{ padding: '0.5rem 0.75rem', fontWeight: 600 }}>{row.make_n}</td>
                        <td style={{ padding: '0.5rem 0.75rem' }}>{row.model_n}</td>
                        <td style={{ padding: '0.5rem 0.75rem' }}>{row.year}</td>
                        <td style={{ padding: '0.5rem 0.75rem', fontWeight: 600, color: !row.is_valid && row.invalid_reason?.includes('Ah') ? R : '#22c55e' }}>
                          {row.ah != null ? `${row.ah} Ah` : '—'}
                        </td>
                        <td style={{ padding: '0.5rem 0.75rem', color: '#6b7280' }}>{row.technology ?? '—'}</td>
                        <td style={{ padding: '0.5rem 0.75rem', color: '#6b7280' }}>{row.source ? (PROVIDER_LABELS[row.source] ?? row.source) : '—'}</td>
                        <td style={{ padding: '0.5rem 0.75rem' }}>
                          {!row.is_valid ? (
                            <span title={row.invalid_reason ?? ''} style={{ fontSize: '0.65rem', fontWeight: 700, background: '#fee2e2', color: R, borderRadius: 99, padding: '0.15rem 0.5rem', cursor: 'help' }}>
                              Invalid
                            </span>
                          ) : row.conflict ? (
                            <span style={{ fontSize: '0.65rem', fontWeight: 700, background: '#fef3c7', color: '#92400e', borderRadius: 99, padding: '0.15rem 0.5rem' }}>
                              Conflict
                            </span>
                          ) : (
                            <span style={{ fontSize: '0.65rem', fontWeight: 700, background: '#dcfce7', color: '#16a34a', borderRadius: 99, padding: '0.15rem 0.5rem' }}>
                              Valid
                            </span>
                          )}
                        </td>
                        <td style={{ padding: '0.5rem 0.75rem' }}>
                          <button
                            onClick={() => {
                              setEditingRow(row)
                              setEditAh(row.ah != null ? String(row.ah) : '')
                              setEditTech(row.technology ?? '')
                              setEditError(null)
                            }}
                            title="Edit Ah / Technology"
                            style={{ background: 'none', border: '1px solid #d1d5db', borderRadius: 4, padding: '0.15rem 0.4rem', cursor: 'pointer', fontSize: '0.7rem', color: '#4b5563' }}
                          >
                            ✏
                          </button>
                        </td>
                      </tr>
                      {/* Conflict detail row */}
                      {row.conflict && row.conflict_detail && (
                        <tr key={`${row.make_n}-${row.model_n}-${row.year}-conflict`}
                          style={{ background: '#fffbeb', borderBottom: '1px solid #fcd34d' }}>
                          <td colSpan={8} style={{ padding: '0.35rem 0.75rem 0.5rem 1.5rem' }}>
                            <div style={{ display: 'flex', gap: '1.5rem', fontSize: '0.68rem', color: '#92400e' }}>
                              <div>
                                <span style={{ fontWeight: 700 }}>Current master: </span>
                                Ah {row.conflict_detail.current.ah ?? '—'} · {row.conflict_detail.current.technology ?? '—'} · {row.conflict_detail.current.source}
                              </div>
                              <div>
                                <span style={{ fontWeight: 700 }}>Staged: </span>
                                Ah {row.conflict_detail.staged.ah ?? '—'} · {row.conflict_detail.staged.technology ?? '—'} · {row.conflict_detail.staged.source}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Staging pagination */}
          {(stagingInfo.total > 50) && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.75rem', justifyContent: 'flex-end' }}>
              <span style={{ fontSize: '0.7rem', color: '#6b7280' }}>
                {((stagingPage - 1) * 50) + 1}–{Math.min(stagingPage * 50, stagingInfo.total)} of {stagingInfo.total.toLocaleString()}
              </span>
              <button disabled={stagingPage === 1} onClick={() => handleStagingPageChange(stagingPage - 1)}
                style={{ padding: '0.3rem', border: '1px solid #e2e4e9', borderRadius: 6, background: '#fff', cursor: stagingPage === 1 ? 'not-allowed' : 'pointer', opacity: stagingPage === 1 ? 0.4 : 1 }}>
                <ChevronLeftIcon style={{ width: 14, height: 14 }} />
              </button>
              <button disabled={stagingPage * 50 >= stagingInfo.total} onClick={() => handleStagingPageChange(stagingPage + 1)}
                style={{ padding: '0.3rem', border: '1px solid #e2e4e9', borderRadius: 6, background: '#fff', cursor: stagingPage * 50 >= stagingInfo.total ? 'not-allowed' : 'pointer', opacity: stagingPage * 50 >= stagingInfo.total ? 0.4 : 1 }}>
                <ChevronRightIcon style={{ width: 14, height: 14 }} />
              </button>
            </div>
          )}

          {/* Action buttons */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', marginTop: '1rem', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
            <button
              onClick={() => { if (window.confirm('Discard all staged data? This will remove the staged records from the master table and cannot be undone.')) handleDiscard() }}
              disabled={discardLoading}
              style={{
                display: 'flex', alignItems: 'center', gap: '0.4rem',
                fontSize: '0.78rem', fontWeight: 700,
                padding: '0.55rem 1.1rem', borderRadius: 9, cursor: discardLoading ? 'not-allowed' : 'pointer',
                border: `1px solid ${R}`, background: '#fff', color: R, opacity: discardLoading ? 0.6 : 1,
              }}
            >
              <TrashIcon style={{ width: 13, height: 13 }} />
              {discardLoading ? 'Discarding…' : 'Discard All'}
            </button>
            <button
              onClick={handleOpenCommitModal}
              style={{
                display: 'flex', alignItems: 'center', gap: '0.4rem',
                fontSize: '0.78rem', fontWeight: 700,
                padding: '0.55rem 1.1rem', borderRadius: 9, cursor: 'pointer',
                border: 'none', background: '#3b82f6', color: '#fff',
              }}
            >
              <ServerStackIcon style={{ width: 13, height: 13 }} />
              Review &amp; Commit
            </button>
          </div>
        </div>
      )}

      {/* Version History Panel */}
      <div style={{ ...CARD, padding: '1rem 1.5rem' }}>
        <div
          style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', userSelect: 'none' }}
          onClick={() => setShowVersions(v => !v)}
        >
          <h3 style={{ margin: 0, fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.8)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <ServerStackIcon style={{ width: 13, height: 13 }} />
            Version History {versionsTotal > 0 ? `(${versionsTotal})` : ''}
          </h3>
          <span style={{ fontSize: '0.75rem', color: '#6b7280' }}>{showVersions ? '▲' : '▼'}</span>
        </div>

        {showVersions && (
          <div style={{ marginTop: '0.85rem' }}>
            {versionsLoading ? (
              <p style={{ margin: 0, fontSize: '0.75rem', color: '#9ca3af' }}>Loading…</p>
            ) : versions.length === 0 ? (
              <p style={{ margin: 0, fontSize: '0.75rem', color: '#9ca3af' }}>No committed versions yet.</p>
            ) : (
              <>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.74rem' }}>
                    <thead>
                      <tr style={{ background: '#f4f5f7' }}>
                        {['Version', 'Committed At', 'Committed By', 'Pipeline Run By', 'Committed', 'Removed', 'Conflicts', ''].map(col => (
                          <th key={col} style={{ padding: '0.5rem 0.75rem', textAlign: 'left', fontWeight: 700, color: 'rgba(107,114,128,0.9)', fontSize: '0.65rem', textTransform: 'uppercase', letterSpacing: '0.07em', whiteSpace: 'nowrap' }}>
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {versions.map((v, i) => (
                        <tr key={v.id} style={{ background: i % 2 === 0 ? '#fff' : '#f9fafb', borderBottom: '1px solid #e2e4e9' }}>
                          <td style={{ padding: '0.5rem 0.75rem', fontWeight: 700, color: '#3b82f6' }}>
                            #{v.version_number}
                            {v.notes && (
                              <span style={{ marginLeft: 6, fontSize: '0.6rem', fontWeight: 600, background: '#fef3c7', color: '#92400e', borderRadius: 99, padding: '0.1rem 0.4rem' }}>
                                revert
                              </span>
                            )}
                          </td>
                          <td style={{ padding: '0.5rem 0.75rem', color: '#6b7280' }}>{new Date(v.committed_at).toLocaleString()}</td>
                          <td style={{ padding: '0.5rem 0.75rem', color: '#374151', fontWeight: 600, fontSize: '0.72rem' }}>{v.committed_by ?? '—'}</td>
                          <td style={{ padding: '0.5rem 0.75rem', color: '#6b7280', fontSize: '0.72rem' }}>{v.initiated_by ?? '—'}</td>
                          <td style={{ padding: '0.5rem 0.75rem', color: '#22c55e', fontWeight: 600 }}>{v.committed_count}</td>
                          <td style={{ padding: '0.5rem 0.75rem', color: v.removed_count > 0 ? R : '#9ca3af' }}>{v.removed_count}</td>
                          <td style={{ padding: '0.5rem 0.75rem', color: v.conflict_count > 0 ? '#f59e0b' : '#9ca3af' }}>{v.conflict_count}</td>
                          <td style={{ padding: '0.5rem 0.75rem', display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                            <button
                              onClick={() => handleOpenChangelog(v.id)}
                              style={{ fontSize: '0.7rem', fontWeight: 600, color: '#3b82f6', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                            >
                              View Diff
                            </button>
                            <button
                              onClick={() => handleRevert(v)}
                              disabled={revertingId === v.id}
                              title={`Undo the changes made by version #${v.version_number}`}
                              style={{
                                fontSize: '0.7rem', fontWeight: 600,
                                color: revertingId === v.id ? '#9ca3af' : R,
                                background: 'none', border: 'none',
                                cursor: revertingId === v.id ? 'not-allowed' : 'pointer',
                                padding: 0, display: 'flex', alignItems: 'center', gap: 2,
                              }}
                            >
                              {revertingId === v.id
                                ? <ArrowSpinner />
                                : <ArrowPathIcon style={{ width: 11, height: 11 }} />
                              }
                              Revert
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {versionsTotal > 20 && (
                  <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', marginTop: '0.75rem' }}>
                    <button disabled={versionsPage === 1} onClick={() => fetchVersions(versionsPage - 1)}
                      style={{ padding: '0.3rem', border: '1px solid #e2e4e9', borderRadius: 6, background: '#fff', cursor: versionsPage === 1 ? 'not-allowed' : 'pointer', opacity: versionsPage === 1 ? 0.4 : 1 }}>
                      <ChevronLeftIcon style={{ width: 14, height: 14 }} />
                    </button>
                    <button disabled={versionsPage * 20 >= versionsTotal} onClick={() => fetchVersions(versionsPage + 1)}
                      style={{ padding: '0.3rem', border: '1px solid #e2e4e9', borderRadius: 6, background: '#fff', cursor: versionsPage * 20 >= versionsTotal ? 'not-allowed' : 'pointer', opacity: versionsPage * 20 >= versionsTotal ? 0.4 : 1 }}>
                      <ChevronRightIcon style={{ width: 14, height: 14 }} />
                    </button>
                  </div>
                )}
              </>
            )}

            {/* Inline changelog drawer */}
            {openChangelog && (
              <div style={{ marginTop: '1rem', background: '#f9fafb', border: '1px solid #e2e4e9', borderRadius: 10, padding: '1rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                  <span style={{ fontSize: '0.75rem', fontWeight: 700, color: '#374151' }}>
                    Changelog for Version #{openChangelog.version.version_number}
                  </span>
                  <button onClick={() => setOpenChangelog(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280' }}>
                    <XMarkIcon style={{ width: 14, height: 14 }} />
                  </button>
                </div>
                {changelogLoading ? (
                  <p style={{ fontSize: '0.75rem', color: '#9ca3af', margin: 0 }}>Loading…</p>
                ) : (
                  <div style={{ overflowX: 'auto', maxHeight: 320, overflowY: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.72rem' }}>
                      <thead>
                        <tr style={{ background: '#e5e7eb' }}>
                          {['Type', 'Make', 'Model', 'Year', 'Before', 'After'].map(col => (
                            <th key={col} style={{ padding: '0.4rem 0.6rem', textAlign: 'left', fontWeight: 700, color: '#374151', fontSize: '0.63rem', textTransform: 'uppercase' }}>
                              {col}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {openChangelog.items.map((entry, i) => (
                          <tr key={i} style={{ background: i % 2 === 0 ? '#fff' : '#f9fafb', borderBottom: '1px solid #e5e7eb' }}>
                            <td style={{ padding: '0.4rem 0.6rem' }}>
                              <span style={{
                                fontSize: '0.62rem', fontWeight: 700, borderRadius: 99, padding: '0.1rem 0.4rem',
                                background: entry.change_type === 'added' ? '#dcfce7' : entry.change_type === 'removed' ? '#fee2e2' : '#dbeafe',
                                color: entry.change_type === 'added' ? '#16a34a' : entry.change_type === 'removed' ? R : '#1d4ed8',
                              }}>
                                {entry.change_type}
                              </span>
                            </td>
                            <td style={{ padding: '0.4rem 0.6rem', fontWeight: 600 }}>{entry.make_n}</td>
                            <td style={{ padding: '0.4rem 0.6rem' }}>{entry.model_n}</td>
                            <td style={{ padding: '0.4rem 0.6rem' }}>{entry.year}</td>
                            <td style={{ padding: '0.4rem 0.6rem', color: '#9ca3af', fontFamily: 'monospace', fontSize: '0.68rem' }}>
                              {entry.old_values ? `${entry.old_values.ah}Ah ${entry.old_values.technology}` : '—'}
                            </td>
                            <td style={{ padding: '0.4rem 0.6rem', color: '#22c55e', fontFamily: 'monospace', fontSize: '0.68rem' }}>
                              {entry.new_values ? `${entry.new_values.ah}Ah ${entry.new_values.technology}` : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Matched Vehicles panel */}
      {matchedCount > 0 && (
        <div style={{ ...CARD, padding: '1.25rem 1.5rem' }}>
          <div
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', userSelect: 'none' }}
            onClick={() => setShowMatched(p => !p)}
          >
            <h3 style={{ margin: 0, fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.8)' }}>
              Matched Vehicles ({matchedCount.toLocaleString()})
            </h3>
            <span style={{ fontSize: '0.75rem', color: '#6b7280' }}>{showMatched ? '▲' : '▼'}</span>
          </div>

          {showMatched && (
            <div style={{ marginTop: '1rem' }}>
              {/* Search */}
              <div style={{ position: 'relative', marginBottom: '0.75rem', maxWidth: 300 }}>
                <MagnifyingGlassIcon style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', width: 14, height: 14, color: '#9ca3af' }} />
                <input
                  value={matchedSearch}
                  onChange={e => handleMatchedSearchChange(e.target.value)}
                  placeholder="Filter by make or model…"
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    paddingLeft: 32, paddingRight: 10, paddingTop: 7, paddingBottom: 7,
                    border: '1px solid #e2e4e9', borderRadius: 8,
                    fontSize: '0.78rem', outline: 'none',
                    fontFamily: "'Segoe UI', system-ui, sans-serif",
                  }}
                />
              </div>

              {/* Table */}
              {matchedLoading ? (
                <p style={{ margin: 0, fontSize: '0.75rem', color: '#9ca3af' }}>Loading…</p>
              ) : (
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.75rem' }}>
                    <thead>
                      <tr style={{ background: '#f4f5f7' }}>
                        {['Make', 'Model', 'Year', 'Ah', 'Technology', 'Source'].map(col => (
                          <th key={col} style={{ padding: '0.5rem 0.75rem', textAlign: 'left', fontWeight: 700, color: 'rgba(107,114,128,0.9)', fontSize: '0.65rem', textTransform: 'uppercase', letterSpacing: '0.07em', whiteSpace: 'nowrap' }}>
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(matchedData?.items.length ?? 0) === 0 ? (
                        <tr><td colSpan={6} style={{ padding: '1rem', textAlign: 'center', color: '#9ca3af' }}>No results</td></tr>
                      ) : matchedData!.items.map((v, i) => (
                        <tr key={i} style={{ background: i % 2 === 0 ? '#fff' : '#f9fafb', borderBottom: '1px solid #e2e4e9' }}>
                          <td style={{ padding: '0.5rem 0.75rem', fontWeight: 600 }}>{v.make_n}</td>
                          <td style={{ padding: '0.5rem 0.75rem' }}>{v.model_n}</td>
                          <td style={{ padding: '0.5rem 0.75rem' }}>{v.year}</td>
                          <td style={{ padding: '0.5rem 0.75rem', color: '#22c55e', fontWeight: 600 }}>{v.ah != null ? `${v.ah} Ah` : '—'}</td>
                          <td style={{ padding: '0.5rem 0.75rem', color: '#6b7280' }}>{v.technology ?? '—'}</td>
                          <td style={{ padding: '0.5rem 0.75rem', color: '#6b7280' }}>{v.source ? (PROVIDER_LABELS[v.source] ?? v.source) : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Pagination */}
              {matchedData && matchedData.total > matchedData.page_size && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.75rem', justifyContent: 'flex-end' }}>
                  <span style={{ fontSize: '0.7rem', color: '#6b7280' }}>
                    {((matchedPage - 1) * 50) + 1}–{Math.min(matchedPage * 50, matchedData.total)} of {matchedData.total.toLocaleString()}
                  </span>
                  <button
                    disabled={matchedPage === 1}
                    onClick={() => setMatchedPage(p => p - 1)}
                    style={{ padding: '0.3rem', border: '1px solid #e2e4e9', borderRadius: 6, background: '#fff', cursor: matchedPage === 1 ? 'not-allowed' : 'pointer', opacity: matchedPage === 1 ? 0.4 : 1 }}
                  >
                    <ChevronLeftIcon style={{ width: 14, height: 14 }} />
                  </button>
                  <button
                    disabled={matchedPage * 50 >= matchedData.total}
                    onClick={() => setMatchedPage(p => p + 1)}
                    style={{ padding: '0.3rem', border: '1px solid #e2e4e9', borderRadius: 6, background: '#fff', cursor: matchedPage * 50 >= matchedData.total ? 'not-allowed' : 'pointer', opacity: matchedPage * 50 >= matchedData.total ? 0.4 : 1 }}
                  >
                    <ChevronRightIcon style={{ width: 14, height: 14 }} />
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {unmatchedCount > 0 && (
        <div style={{ ...CARD, padding: '1.25rem 1.5rem' }}>
          <div
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', userSelect: 'none' }}
            onClick={() => setShowUnmatched(p => !p)}
          >
            <h3 style={{ margin: 0, fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.8)' }}>
              Unmatched Vehicles ({unmatchedCount.toLocaleString()})
            </h3>
            <span style={{ fontSize: '0.75rem', color: '#6b7280' }}>{showUnmatched ? '▲' : '▼'}</span>
          </div>

          {showUnmatched && (
            <div style={{ marginTop: '1rem' }}>
              {/* Search */}
              <div style={{ position: 'relative', marginBottom: '0.75rem', maxWidth: 300 }}>
                <MagnifyingGlassIcon style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', width: 14, height: 14, color: '#9ca3af' }} />
                <input
                  value={coverageSearch}
                  onChange={e => handleSearchChange(e.target.value)}
                  placeholder="Filter by make or model…"
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    paddingLeft: 32, paddingRight: 10, paddingTop: 7, paddingBottom: 7,
                    border: '1px solid #e2e4e9', borderRadius: 8,
                    fontSize: '0.78rem', outline: 'none',
                    fontFamily: "'Segoe UI', system-ui, sans-serif",
                  }}
                />
              </div>

              {/* Table */}
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.75rem' }}>
                  <thead>
                    <tr style={{ background: '#f4f5f7' }}>
                      {['Make', 'Model', 'Year', 'Engine CC', 'Fuel Type'].map(col => (
                        <th key={col} style={{ padding: '0.5rem 0.75rem', textAlign: 'left', fontWeight: 700, color: 'rgba(107,114,128,0.9)', fontSize: '0.65rem', textTransform: 'uppercase', letterSpacing: '0.07em', whiteSpace: 'nowrap' }}>
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {pagedRows.length === 0 ? (
                      <tr><td colSpan={5} style={{ padding: '1rem', textAlign: 'center', color: '#9ca3af' }}>No results</td></tr>
                    ) : pagedRows.map((v, i) => (
                      <tr key={i} style={{ background: i % 2 === 0 ? '#fff' : '#f9fafb', borderBottom: '1px solid #e2e4e9' }}>
                        <td style={{ padding: '0.5rem 0.75rem', fontWeight: 600 }}>{v.make_n}</td>
                        <td style={{ padding: '0.5rem 0.75rem' }}>{v.model_n}</td>
                        <td style={{ padding: '0.5rem 0.75rem' }}>{v.year}</td>
                        <td style={{ padding: '0.5rem 0.75rem', color: '#6b7280' }}>{v.engine_cc ?? '—'}</td>
                        <td style={{ padding: '0.5rem 0.75rem', color: '#6b7280' }}>{v.fuel_type ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.75rem', justifyContent: 'flex-end' }}>
                  <span style={{ fontSize: '0.7rem', color: '#6b7280' }}>
                    {((coveragePage - 1) * COVERAGE_PAGE_SIZE) + 1}–{Math.min(coveragePage * COVERAGE_PAGE_SIZE, filteredUnmatched.length)} of {filteredUnmatched.length.toLocaleString()}
                  </span>
                  <button
                    disabled={coveragePage === 1}
                    onClick={() => setCoveragePage(p => p - 1)}
                    style={{ padding: '0.3rem', border: '1px solid #e2e4e9', borderRadius: 6, background: '#fff', cursor: coveragePage === 1 ? 'not-allowed' : 'pointer', opacity: coveragePage === 1 ? 0.4 : 1 }}
                  >
                    <ChevronLeftIcon style={{ width: 14, height: 14 }} />
                  </button>
                  <button
                    disabled={coveragePage === totalPages}
                    onClick={() => setCoveragePage(p => p + 1)}
                    style={{ padding: '0.3rem', border: '1px solid #e2e4e9', borderRadius: 6, background: '#fff', cursor: coveragePage === totalPages ? 'not-allowed' : 'pointer', opacity: coveragePage === totalPages ? 0.4 : 1 }}
                  >
                    <ChevronRightIcon style={{ width: 14, height: 14 }} />
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Quota Status */}
      <div style={{ ...CARD, padding: '1.25rem 1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.4rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <h3 style={{ margin: 0, fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.8)' }}>
              API Quota — {new Date().toISOString().slice(0, 7)}
            </h3>
            <button
              onClick={handleRefreshQuotas}
              disabled={loadingQuotas}
              title="Refresh quota data"
              style={{
                background: 'none', border: 'none', cursor: loadingQuotas ? 'not-allowed' : 'pointer',
                padding: 3, borderRadius: 6, color: '#9ca3af', opacity: loadingQuotas ? 0.4 : 1,
                display: 'flex', alignItems: 'center',
              }}
            >
              <ArrowPathIcon style={{ width: 13, height: 13, animation: loadingQuotas ? 'spin 1s linear infinite' : 'none' }} />
            </button>
          </div>
          <span style={{ fontSize: '0.65rem', color: '#9ca3af' }}>
            Resets {new Date(new Date().getFullYear(), new Date().getMonth() + 1, 1).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}
          </span>
        </div>

        {quotas.length === 0 ? (
          <p style={{ margin: 0, fontSize: '0.75rem', color: '#9ca3af' }}>No quota data yet — quota rows are created on the first pipeline run.</p>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: '0.75rem' }}>
            {quotas.map(q => <QuotaCard key={q.provider} info={q} />)}
          </div>
        )}

        {anyAtWarning && !allLimitedOut && (
          <div style={{ marginTop: '0.85rem', display: 'flex', alignItems: 'flex-start', gap: '0.5rem', background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: 8, padding: '0.6rem 0.85rem' }}>
            <ExclamationCircleIcon style={{ width: 15, height: 15, color: '#f59e0b', flexShrink: 0, marginTop: 1 }} />
            <span style={{ fontSize: '0.73rem', color: '#92400e' }}>One or more paid search providers are approaching their monthly quota. DuckDuckGo remains available as an unlimited fallback.</span>
          </div>
        )}

        {allLimitedOut && (
          <div style={{ marginTop: '0.85rem', display: 'flex', alignItems: 'flex-start', gap: '0.5rem', background: '#fff5f5', border: `1px solid ${R}`, borderRadius: 8, padding: '0.6rem 0.85rem' }}>
            <ExclamationCircleIcon style={{ width: 15, height: 15, color: R, flexShrink: 0, marginTop: 1 }} />
            <span style={{ fontSize: '0.73rem', color: '#7f1d1d' }}>Google CSE and Tavily quotas are exhausted. The pipeline will continue using DuckDuckGo (unlimited).</span>
          </div>
        )}
      </div>

      {/* ── Edit Staging Row Modal ── */}
      {editingRow && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem' }}>
          <div style={{ ...CARD, padding: '1.5rem', maxWidth: 360, width: '100%' }}>
            <h2 style={{ margin: '0 0 0.1rem', fontSize: '0.95rem', fontWeight: 700, color: '#111827' }}>
              Edit Staged Row
            </h2>
            <p style={{ margin: '0 0 1rem', fontSize: '0.72rem', color: '#6b7280' }}>
              {editingRow.make_n} {editingRow.model_n} {editingRow.year}
            </p>

            <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 600, color: '#374151', marginBottom: '0.25rem' }}>
              Ah (20–250, leave blank for none)
            </label>
            <input
              type="number"
              value={editAh}
              onChange={e => setEditAh(e.target.value)}
              min={20} max={250} step={1}
              style={{ width: '100%', boxSizing: 'border-box', border: '1px solid #d1d5db', borderRadius: 6, padding: '0.4rem 0.6rem', fontSize: '0.82rem', marginBottom: '0.75rem' }}
            />

            <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 600, color: '#374151', marginBottom: '0.25rem' }}>
              Technology
            </label>
            <select
              value={editTech}
              onChange={e => setEditTech(e.target.value)}
              style={{ width: '100%', border: '1px solid #d1d5db', borderRadius: 6, padding: '0.4rem 0.6rem', fontSize: '0.82rem', marginBottom: '1rem' }}
            >
              <option value="">— none —</option>
              {['MF', 'AGM', 'EFB', 'GEL', 'WET'].map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>

            {editError && (
              <p style={{ margin: '0 0 0.75rem', fontSize: '0.72rem', color: '#dc2626', background: '#fee2e2', borderRadius: 6, padding: '0.4rem 0.6rem' }}>
                {editError}
              </p>
            )}

            <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
              <button
                onClick={() => setEditingRow(null)}
                disabled={editSaving}
                style={{ padding: '0.4rem 0.9rem', borderRadius: 6, border: '1px solid #d1d5db', background: '#fff', cursor: 'pointer', fontSize: '0.8rem' }}
              >
                Cancel
              </button>
              <button
                onClick={handleSaveEdit}
                disabled={editSaving}
                style={{ padding: '0.4rem 0.9rem', borderRadius: 6, border: 'none', background: '#3b82f6', color: '#fff', cursor: editSaving ? 'not-allowed' : 'pointer', fontSize: '0.8rem', fontWeight: 600, opacity: editSaving ? 0.7 : 1 }}
              >
                {editSaving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Commit Modal ── */}
      {commitModalOpen && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem' }}>
          <div style={{ ...CARD, padding: '1.5rem', maxWidth: 560, width: '100%', maxHeight: '85vh', overflowY: 'auto' }}>
            <h2 style={{ margin: '0 0 0.75rem', fontSize: '1rem', fontWeight: 700, color: '#111827' }}>
              Commit Staged Data to Master Table
            </h2>

            {commitResult ? (
              <>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8, padding: '0.75rem 1rem', marginBottom: '1rem' }}>
                  <CheckCircleIcon style={{ width: 16, height: 16, color: '#22c55e', flexShrink: 0, marginTop: 1 }} />
                  <p style={{ margin: 0, fontSize: '0.8rem', color: '#14532d' }}>
                    <strong>Version #{commitResult.version_number} created.</strong><br />
                    {commitResult.committed} records committed · {commitResult.removed_invalid} invalid removed · {commitResult.conflicts_resolved} conflicts resolved.
                  </p>
                </div>
                <button
                  onClick={() => setCommitModalOpen(false)}
                  style={{ padding: '0.6rem 1.25rem', borderRadius: 9, border: 'none', background: '#3b82f6', color: '#fff', fontWeight: 700, fontSize: '0.82rem', cursor: 'pointer' }}
                >
                  Close
                </button>
              </>
            ) : (
              <>
                {stagingInfo && (
                  <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
                    <span style={{ fontSize: '0.72rem', fontWeight: 600, background: '#dcfce7', color: '#16a34a', borderRadius: 99, padding: '0.2rem 0.6rem' }}>
                      {stagingInfo.valid_count} valid → will commit
                    </span>
                    {stagingInfo.invalid_count > 0 && (
                      <span style={{ fontSize: '0.72rem', fontWeight: 600, background: '#fee2e2', color: R, borderRadius: 99, padding: '0.2rem 0.6rem' }}>
                        {stagingInfo.invalid_count} invalid → will remove from master
                      </span>
                    )}
                    {stagingInfo.conflict_count > 0 && (
                      <span style={{ fontSize: '0.72rem', fontWeight: 600, background: '#fef3c7', color: '#92400e', borderRadius: 99, padding: '0.2rem 0.6rem' }}>
                        {stagingInfo.conflict_count} conflicts → resolve below
                      </span>
                    )}
                  </div>
                )}

                {/* Conflict resolution */}
                {preCommitConflicts.length > 0 && (
                  <div style={{ marginBottom: '1rem' }}>
                    <p style={{ margin: '0 0 0.5rem', fontSize: '0.75rem', fontWeight: 700, color: '#92400e' }}>
                      Resolve conflicts — choose which value to keep:
                    </p>
                    {preCommitConflicts.map(c => {
                      const key = `${c.make_n}|${c.model_n}|${c.year}`
                      const choice = conflictResolutions[key] ?? 'staging'
                      return (
                        <div key={key} style={{ background: '#fffbeb', border: '1px solid #fcd34d', borderRadius: 8, padding: '0.65rem 0.85rem', marginBottom: '0.5rem' }}>
                          <p style={{ margin: '0 0 0.4rem', fontSize: '0.78rem', fontWeight: 700, color: '#374151' }}>
                            {c.make_n} {c.model_n} {c.year}
                          </p>
                          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                            {(['staging', 'current'] as const).map(opt => (
                              <label key={opt} style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.72rem', cursor: 'pointer' }}>
                                <input type="radio" name={key} value={opt} checked={choice === opt}
                                  onChange={() => setConflictResolutions(prev => ({ ...prev, [key]: opt }))} />
                                <span style={{ fontWeight: 600 }}>{opt === 'staging' ? 'Use Staged' : 'Keep Current'}:</span>
                                <span style={{ color: '#6b7280' }}>
                                  {opt === 'staging'
                                    ? `Ah ${c.conflict_detail.staged.ah ?? '—'} · ${c.conflict_detail.staged.technology ?? '—'} · ${c.conflict_detail.staged.source}`
                                    : `Ah ${c.conflict_detail.current.ah ?? '—'} · ${c.conflict_detail.current.technology ?? '—'} · ${c.conflict_detail.current.source}`
                                  }
                                </span>
                              </label>
                            ))}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}

                <div style={{ display: 'flex', gap: '0.65rem', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                  <button onClick={() => setCommitModalOpen(false)}
                    style={{ padding: '0.6rem 1.1rem', borderRadius: 9, border: '1px solid #e2e4e9', background: '#fff', color: '#374151', fontWeight: 600, fontSize: '0.8rem', cursor: 'pointer' }}>
                    Cancel
                  </button>
                  <button
                    onClick={handleCommit}
                    disabled={commitLoading}
                    style={{ padding: '0.6rem 1.25rem', borderRadius: 9, border: 'none', background: commitLoading ? '#9ca3af' : '#3b82f6', color: '#fff', fontWeight: 700, fontSize: '0.82rem', cursor: commitLoading ? 'not-allowed' : 'pointer' }}>
                    {commitLoading ? 'Committing…' : 'Confirm & Commit'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* ── Navigation Blocker Modal ── */}
      {blocker.state === 'blocked' && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem' }}>
          <div style={{ ...CARD, padding: '1.5rem', maxWidth: 440, width: '100%' }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem', marginBottom: '1rem' }}>
              <ExclamationCircleIcon style={{ width: 22, height: 22, color: '#f59e0b', flexShrink: 0 }} />
              <div>
                <h2 style={{ margin: '0 0 0.4rem', fontSize: '0.95rem', fontWeight: 700, color: '#111827' }}>
                  Unsaved Staged Data
                </h2>
                <p style={{ margin: 0, fontSize: '0.8rem', color: '#6b7280', lineHeight: 1.6 }}>
                  You have unreviewed staged data. Navigating away will permanently discard all staged data from the master table.
                </p>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '0.65rem', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
              <button
                onClick={() => blocker.reset?.()}
                style={{ padding: '0.6rem 1.1rem', borderRadius: 9, border: '1px solid #e2e4e9', background: '#fff', color: '#374151', fontWeight: 600, fontSize: '0.8rem', cursor: 'pointer' }}
              >
                Stay on Page
              </button>
              <button
                onClick={async () => {
                  await discardStagingArea().catch(() => {})
                  setStagingInfo(null)
                  blocker.proceed?.()
                }}
                style={{ padding: '0.6rem 1.1rem', borderRadius: 9, border: 'none', background: R, color: '#fff', fontWeight: 700, fontSize: '0.8rem', cursor: 'pointer' }}
              >
                Discard &amp; Leave
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function getProgressBarColor(pct: number, paused: boolean): string {
  if (paused) return '#f59e0b'
  // red #ef4444 rgb(239,68,68) → blue #3b82f6 rgb(59,130,246) → green #22c55e rgb(34,197,94)
  if (pct <= 50) {
    const t = pct / 50
    return `rgb(${Math.round(239 + (59 - 239) * t)},${Math.round(68 + (130 - 68) * t)},${Math.round(68 + (246 - 68) * t)})`
  }
  const t = (pct - 50) / 50
  return `rgb(${Math.round(59 + (34 - 59) * t)},${Math.round(130 + (197 - 130) * t)},${Math.round(246 + (94 - 246) * t)})`
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
          <div style={{ display: 'flex', gap: '0.5rem', background: '#f4f5f7', padding: '0.3rem', borderRadius: 99, width: 'fit-content', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
            <button style={tabStyle('crsp')} onClick={() => setActiveTab('crsp')}>
              <TableCellsIcon style={{ width: 14, height: 14 }} /> CRSP Dataset
            </button>
            <button style={tabStyle('ntsa')} onClick={() => setActiveTab('ntsa')}>
              <DocumentMagnifyingGlassIcon style={{ width: 14, height: 14 }} /> NTSA Dataset
            </button>
            <button style={tabStyle('webvalidate')} onClick={() => setActiveTab('webvalidate')}>
              <GlobeAltIcon style={{ width: 14, height: 14 }} /> Web Validate
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
          ) : activeTab === 'ntsa' ? (
            <PipelineTab
              key="ntsa"
              dataset="NTSA"
              stages={NTSA_STAGES}
              fileAccept=".xlsx,.xls,.csv"
              dropLabel="Drop your NTSA vehicle registration dataset here"
              info="The NTSA pipeline validates plate numbers, normalises fuel types and make/model fields, filters invalid year-of-manufacture values, deduplicates by plate number, and merges battery recommendations from the cleaned CRSP data."
            />
          ) : (
            <WebValidateTab />
          )}
        </div>

      </main>
    </AdminLayout>
  )
}
