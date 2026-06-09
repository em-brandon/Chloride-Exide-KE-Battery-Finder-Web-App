import { useState, useEffect, useRef } from 'react'
import {
  PlayIcon, StopCircleIcon, CheckCircleIcon, ArrowPathIcon, ClockIcon,
  ExclamationCircleIcon, CheckBadgeIcon, ArrowUpTrayIcon, XMarkIcon,
  DocumentIcon,
} from '@heroicons/react/24/solid'
import { api } from '../lib/api'

const R = '#CC0000'
const CARD: React.CSSProperties = {
  background: '#fff', borderRadius: 14, border: '1px solid #e2e4e9',
  boxShadow: '0 2px 12px rgba(0,0,0,0.07)', padding: '1.25rem',
}

type Status = 'idle' | 'running' | 'done' | 'error' | 'cancelled'

interface CrspState {
  status: Status
  stage: string | null
  total_rows: number
  clean_rows: number
  rejected: number
  duplicates: number
  logs: string[]
  started_at: string | null
  finished_at: string | null
  error_detail: string | null
  output_csv: string | null
}

const STAGES = ['Loading', 'Schema', 'Normalizing', 'Dedup', 'Saving']

function stageIndex(stage: string | null): number {
  if (!stage) return -1
  const s = stage.toLowerCase()
  return STAGES.findIndex(st => s.startsWith(st.toLowerCase()))
}

function logColor(line: string): string {
  if (line.includes('[OK]') || line.includes('✓')) return '#15803d'
  if (line.includes('[ERROR]') || line.includes('✗')) return '#dc2626'
  if (line.includes('[WARN]')) return '#b45309'
  return '#374151'
}

export function CrspPage() {
  const [file, setFile]           = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [serverPath, setServerPath] = useState('')
  const [dragging, setDragging]   = useState(false)
  const [state, setState]         = useState<CrspState | null>(null)
  const [polling, setPolling]     = useState(false)
  const [error, setError]         = useState('')
  const logRef  = useRef<HTMLDivElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    api.crspStatus().then(s => setState(s as unknown as CrspState)).catch(() => {})
  }, [])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [state?.logs])

  function startPolling() {
    setPolling(true)
    intervalRef.current = setInterval(async () => {
      try {
        const s = await api.crspStatus() as unknown as CrspState
        setState(s)
        if (s.status !== 'running') { clearInterval(intervalRef.current!); setPolling(false) }
      } catch {
        clearInterval(intervalRef.current!)
        setPolling(false)
      }
    }, 1500)
  }

  useEffect(() => () => { if (intervalRef.current) clearInterval(intervalRef.current) }, [])

  async function handleFileAccepted(f: File) {
    setFile(f)
    setError('')
    setUploading(true)
    try {
      const res = await api.crspUpload(f)
      setServerPath(res.file_path)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Upload failed')
      setFile(null)
    } finally {
      setUploading(false)
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    const dropped = e.dataTransfer.files[0]
    if (dropped) handleFileAccepted(dropped)
  }

  function handleFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0]
    if (picked) handleFileAccepted(picked)
  }

  function clearFile() {
    setFile(null)
    setServerPath('')
    setError('')
    if (fileRef.current) fileRef.current.value = ''
  }

  async function handleRun() {
    if (!serverPath) { setError('Drop an XLSX file above first'); return }
    setError('')
    try {
      await api.crspRun(serverPath)
      startPolling()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to start')
    }
  }

  async function handleCancel() {
    try { await api.crspCancel() } catch { /* ignored */ }
  }

  const running = state?.status === 'running'
  const done    = state?.status === 'done'
  const curIdx  = stageIndex(state?.stage ?? null)
  void polling

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <h1 style={{ fontSize: '1.1rem', fontWeight: 800, color: '#111827' }}>CRSP Dataset Pipeline</h1>

      {/* File upload */}
      <div style={CARD}>
        <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#374151', marginBottom: '0.65rem' }}>
          CRSP Excel File
        </div>

        {/* Drop zone */}
        <input
          ref={fileRef} type="file" accept=".xlsx,.xls"
          style={{ display: 'none' }}
          onChange={handleFileInput}
        />
        <div
          onDragOver={e => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => !file && !running && fileRef.current?.click()}
          style={{
            borderRadius: 12,
            border: dragging ? `2px dashed ${R}` : file ? '2px dashed #22c55e' : '2px dashed #d1d5db',
            background: dragging ? '#fff5f5' : file ? '#f0fdf4' : '#f9fafb',
            padding: '1.5rem',
            textAlign: 'center',
            cursor: file || running ? 'default' : 'pointer',
            transition: 'all 0.18s',
            marginBottom: '0.75rem',
          }}
        >
          {file ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.75rem' }}>
              <DocumentIcon style={{ width: 22, height: 22, color: uploading ? '#9ca3af' : '#22c55e', flexShrink: 0 }} />
              <div style={{ textAlign: 'left', minWidth: 0 }}>
                <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#111827', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 280 }}>
                  {file.name}
                </div>
                <div style={{ fontSize: '0.7rem', color: '#6b7280', marginTop: 2 }}>
                  {uploading
                    ? 'Uploading…'
                    : `${(file.size / 1024).toFixed(1)} KB · ready`}
                </div>
              </div>
              {!running && (
                <button onClick={e => { e.stopPropagation(); clearFile() }}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9ca3af', padding: 4, borderRadius: 6, marginLeft: 'auto' }}>
                  <XMarkIcon style={{ width: 16, height: 16 }} />
                </button>
              )}
            </div>
          ) : (
            <>
              <ArrowUpTrayIcon style={{ width: 28, height: 28, color: '#d1d5db', marginBottom: '0.5rem' }} />
              <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'rgba(17,24,39,0.7)' }}>
                Drop your CRSP Excel file here
              </div>
              <div style={{ fontSize: '0.72rem', color: '#9ca3af', marginTop: '0.25rem' }}>
                or <span style={{ color: R, fontWeight: 600 }}>browse</span> · .xlsx / .xls
              </div>
            </>
          )}
        </div>

        {/* Action buttons */}
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          {!running ? (
            <button
              onClick={handleRun}
              disabled={!serverPath || uploading}
              style={btnStyle(!serverPath || uploading ? '#e5e7eb' : R, !serverPath || uploading ? '#9ca3af' : '#fff')}
            >
              <PlayIcon style={{ width: 15, height: 15 }} />
              Run Pipeline
            </button>
          ) : (
            <button onClick={handleCancel} style={btnStyle('#fff', R, `1.5px solid ${R}`)}>
              <StopCircleIcon style={{ width: 15, height: 15 }} />
              Cancel
            </button>
          )}
        </div>

        {error && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: R, fontSize: '0.78rem', marginTop: '0.5rem' }}>
            <ExclamationCircleIcon style={{ width: 14, height: 14, flexShrink: 0 }} />
            {error}
          </div>
        )}
      </div>

      {/* Stage progress */}
      {state && state.status !== 'idle' && (
        <div style={CARD}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
            <span style={{ fontWeight: 700, fontSize: '0.88rem', color: '#111827' }}>Pipeline Stages</span>
            <StatusBadge status={state.status} />
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
            {STAGES.map((s, i) => {
              const isDone   = i < curIdx || state.status === 'done'
              const isActive = i === curIdx && running
              const isPending = i > curIdx && state.status === 'running'
              return (
                <div key={s} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: '0.35rem',
                    padding: '0.3rem 0.7rem', borderRadius: 20,
                    fontSize: '0.75rem', fontWeight: 600,
                    background: isDone ? '#dcfce7' : isActive ? '#fff5f5' : '#f3f4f6',
                    color: isDone ? '#15803d' : isActive ? R : '#9ca3af',
                    border: isActive ? `1.5px solid ${R}` : '1.5px solid transparent',
                  }}>
                    {isDone
                      ? <CheckCircleIcon style={{ width: 14, height: 14 }} />
                      : isActive
                        ? <ArrowPathIcon style={{ width: 14, height: 14 }} className="spin" />
                        : <ClockIcon style={{ width: 14, height: 14, opacity: isPending ? 0.5 : 0.3 }} />
                    }
                    {s}
                  </div>
                  {i < STAGES.length - 1 && (
                    <div style={{ width: 14, height: 1, background: isDone ? '#86efac' : '#e2e4e9' }} />
                  )}
                </div>
              )
            })}
          </div>
          {state.stage && running && (
            <p style={{ fontSize: '0.75rem', color: '#6b7280', marginTop: '0.5rem' }}>{state.stage}</p>
          )}
        </div>
      )}

      {/* Summary */}
      {done && (
        <div style={{ ...CARD, border: '1.5px solid #bbf7d0', background: '#f0fdf4' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 700, fontSize: '0.88rem', color: '#15803d', marginBottom: '0.75rem' }}>
            <CheckBadgeIcon style={{ width: 20, height: 20 }} />
            Pipeline Complete
          </div>
          <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap' }}>
            {([
              ['Total Rows',  state?.total_rows,   '#374151'],
              ['Clean Rows',  state?.clean_rows,   '#15803d'],
              ['Rejected',    state?.rejected,     R],
              ['Duplicates',  state?.duplicates,   '#92400e'],
            ] as [string, number | undefined, string][]).map(([label, val, color]) => (
              <div key={label} style={{ textAlign: 'center', minWidth: 80 }}>
                <div style={{ fontSize: '1.5rem', fontWeight: 800, color }}>{val ?? 0}</div>
                <div style={{ fontSize: '0.72rem', color: '#6b7280', marginTop: 2 }}>{label}</div>
              </div>
            ))}
          </div>
          {state?.output_csv && (
            <p style={{ fontSize: '0.75rem', color: '#15803d', marginTop: '0.5rem', fontFamily: 'monospace' }}>
              {state.output_csv}
            </p>
          )}
        </div>
      )}

      {/* Error */}
      {state?.status === 'error' && (
        <div style={{ ...CARD, border: '1.5px solid #fecaca', background: '#fff5f5' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontWeight: 700, color: R, fontSize: '0.88rem' }}>
            <ExclamationCircleIcon style={{ width: 18, height: 18 }} />
            Pipeline Error
          </div>
          <p style={{ fontSize: '0.8rem', color: '#b91c1c', marginTop: '0.35rem' }}>{state.error_detail}</p>
        </div>
      )}

      {/* Logs */}
      {state && state.logs && state.logs.length > 0 && (
        <div style={CARD}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.65rem' }}>
            <div style={{ fontWeight: 700, fontSize: '0.85rem', color: '#374151' }}>Logs</div>
            <span style={{ fontSize: '0.7rem', color: '#9ca3af' }}>{state.logs.length} lines</span>
          </div>
          <div ref={logRef} style={{
            background: '#f8f9fb', border: '1px solid #e2e4e9', borderRadius: 8,
            padding: '0.85rem 1rem', height: 260, overflowY: 'auto',
            fontSize: '0.71rem', fontFamily: "'Consolas', 'Courier New', monospace", lineHeight: 1.85,
          }}>
            {state.logs.map((line, i) => (
              <div key={i} style={{ color: logColor(line), borderBottom: i < state.logs.length - 1 ? '1px solid #f1f3f5' : 'none', paddingBottom: '0.1rem' }}>
                {line}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: Status }) {
  const map: Record<Status, [string, string]> = {
    idle:      ['#6b7280', '#f3f4f6'],
    running:   [R,         '#fff5f5'],
    done:      ['#15803d', '#dcfce7'],
    error:     [R,         '#fff5f5'],
    cancelled: ['#92400e', '#fef3c7'],
  }
  const [color, bg] = map[status]
  return (
    <span style={{
      fontSize: '0.72rem', fontWeight: 700, padding: '0.25rem 0.65rem',
      borderRadius: 20, background: bg, color, textTransform: 'capitalize',
    }}>
      {status}
    </span>
  )
}

function btnStyle(bg: string, color: string, border?: string): React.CSSProperties {
  return {
    display: 'flex', alignItems: 'center', gap: '0.35rem',
    background: bg, color, border: border ?? 'none', borderRadius: 8,
    padding: '0.55rem 1.1rem', fontWeight: 700, fontSize: '0.85rem', cursor: 'pointer',
    whiteSpace: 'nowrap',
  }
}
