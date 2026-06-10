import { useState, useEffect, useRef, useCallback } from 'react'
import {
  PlayIcon, PauseIcon, XMarkIcon, BoltIcon, TrashIcon, ArrowUpTrayIcon,
  PencilSquareIcon, CheckCircleIcon, XCircleIcon, ExclamationTriangleIcon,
  ChevronDownIcon, ChevronRightIcon, ArrowUturnLeftIcon, GlobeAltIcon,
} from '@heroicons/react/24/solid'
import { api, type LogEntry, type SessionInfo, type MasterRecord } from '../lib/api'

const R = '#CC0000'
const CARD: React.CSSProperties = {
  background: '#fff', borderRadius: 14, border: '1px solid #e2e4e9',
  boxShadow: '0 2px 12px rgba(0,0,0,0.07)', padding: '1.25rem',
}

// ── Types ──────────────────────────────────────────────────────────────────────

type PipelineStatus = 'idle' | 'running' | 'paused' | 'done' | 'error' | 'cancelled'

interface WvState {
  status: PipelineStatus
  total: number
  processed: number
  phase1_total: number
  phase1_processed: number
  phase2_started_at: string | null
  current_provider: string | null
  current_combo: string | null
  logs: LogEntry[]
  error_detail: string | null
  finished_at: string | null
  has_staging?: boolean
}

interface Provider { provider: string; configured: boolean; always_available: boolean }
interface StagingRow {
  id: number; make_n: string; model_n: string; year: number
  battery_code: string | null; ah: number | null; technology: string | null
  source: string | null; is_valid: boolean; conflict: boolean
  invalid_reason: string | null
  conflict_detail?: { current: Record<string, unknown>; staged: Record<string, unknown> } | null
}
interface StagingResp { has_staging: boolean; total: number; valid_count: number; invalid_count: number; conflict_count: number; items: StagingRow[]; page: number }
interface VersionRow { id: string; version_number: number; committed_at: string; committed_count: number; removed_count: number; conflict_count: number; committed_by: string }
interface QuotaRow { provider: string; calls_made: number; quota_limit: number; pct_used: number; period_end: string | null; days_until_reset: number | null }
interface MatchedResp { total: number; items: MasterRecord[] }

// ── Main component ─────────────────────────────────────────────────────────────

export function WebValidatePage() {
  const [state, setState]         = useState<WvState | null>(null)
  const [providers, setProviders] = useState<Provider[]>([])
  const [enabledProv, setEnabledProv] = useState<string[]>([])
  const [phase, setPhase]         = useState('both')
  const [polling, setPolling]     = useState(false)
  const [coverage, setCoverage]   = useState<Record<string, unknown> | null>(null)
  const [coverageLoading, setCoverageLoading] = useState(true)
  const [quotas, setQuotas]       = useState<QuotaRow[]>([])
  const [staging, setStaging]     = useState<StagingResp | null>(null)
  const [stagingFilter, setStagingFilter] = useState('all')
  const [stagingPage, setStagingPage]     = useState(1)
  const [versions, setVersions]   = useState<{ total: number; items: VersionRow[] } | null>(null)
  const [showVersions, setShowVersions]   = useState(false)
  const [editRow, setEditRow]     = useState<StagingRow | null>(null)
  const [editAh, setEditAh]       = useState('')
  const [editTech, setEditTech]   = useState('')
  const [savingEdit, setSavingEdit] = useState(false)
  const [runPressed, setRunPressed] = useState(false)
  const [committing, setCommitting] = useState(false)
  const [fixingAh, setFixingAh]   = useState(false)
  const [fixResult, setFixResult] = useState<{ fixed: number; unchanged: number; failed: number } | null>(null)
  const [showCommitModal, setShowCommitModal] = useState(false)
  const [preCommitData, setPreCommitData] = useState<{ conflict_count: number; conflicts: unknown[] } | null>(null)
  const [matched, setMatched]           = useState<MatchedResp | null>(null)
  const [matchedPage, setMatchedPage]   = useState(1)
  const [matchedSearch, setMatchedSearch] = useState('')
  const [matchedLoading, setMatchedLoading] = useState(false)
  const [showMatched, setShowMatched]   = useState(false)
  const [sessions, setSessions]         = useState<SessionInfo[]>([])
  const [showSessions, setShowSessions] = useState(false)
  const [revokingId, setRevokingId]     = useState<number | null>(null)
  const [editMasterRow, setEditMasterRow]         = useState<MasterRecord | null>(null)
  const [editMasterAh, setEditMasterAh]           = useState('')
  const [editMasterTech, setEditMasterTech]       = useState('')
  const [editMasterBc, setEditMasterBc]           = useState('')
  const [editMasterScope, setEditMasterScope]     = useState<'single' | 'bucket'>('single')
  const [masterSaveResult, setMasterSaveResult]   = useState<number | null>(null)
  const [savingMasterEdit, setSavingMasterEdit]   = useState(false)
  const [deletingMasterId, setDeletingMasterId]   = useState<number | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const logRef = useRef<HTMLDivElement>(null)
  void polling

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [state?.logs])

  useEffect(() => {
    api.wvStatus().then(s => setState(s as unknown as WvState)).catch(() => {})
    api.wvProviders().then(p => {
      setProviders(p)
      setEnabledProv(p.filter((x: Provider) => x.configured && !x.always_available).map((x: Provider) => x.provider))
    }).catch(() => {})
    api.wvCoverage().then(c => setCoverage(c)).catch(() => {}).finally(() => setCoverageLoading(false))
    api.quotas().then(q => setQuotas(q)).catch(() => {})
    api.staging(1, 'all').then(s => setStaging(s as unknown as StagingResp)).catch(() => {})
    api.sessions().then(setSessions).catch(() => {})
  }, [])

  function startPolling() {
    setPolling(true)
    intervalRef.current = setInterval(async () => {
      try {
        const s = await api.wvStatus() as unknown as WvState
        setState(s)
        if (s.status !== 'running' && s.status !== 'paused') {
          clearInterval(intervalRef.current!)
          setPolling(false)
          api.wvCoverage().then(c => setCoverage(c)).catch(() => {})
          api.quotas().then(q => setQuotas(q)).catch(() => {})
          api.staging(1, stagingFilter).then(s2 => setStaging(s2 as unknown as StagingResp)).catch(() => {})
        }
      } catch {
        clearInterval(intervalRef.current!)
        setPolling(false)
      }
    }, 1500)
  }

  useEffect(() => () => { if (intervalRef.current) clearInterval(intervalRef.current) }, [])

  const loadStaging = useCallback(async (page = stagingPage, filter = stagingFilter) => {
    const s = await api.staging(page, filter) as unknown as StagingResp
    setStaging(s)
  }, [stagingPage, stagingFilter])

  async function handleRun() {
    setRunPressed(true)
    setTimeout(() => setRunPressed(false), 300)
    try {
      await api.wvRun(enabledProv.length ? enabledProv : null, phase)
      startPolling()
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to start pipeline')
    }
  }

  async function handleFixAh() {
    setFixingAh(true); setFixResult(null)
    try {
      const r = await api.fixAh()
      setFixResult(r)
      loadStaging(1, stagingFilter)
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Fix Ah failed')
    } finally { setFixingAh(false) }
  }

  async function handleDiscard() {
    if (!confirm('Discard all staged records? This also removes them from the master table.')) return
    try {
      await api.discard()
      setStaging(null)
      api.wvCoverage().then(c => setCoverage(c)).catch(() => {})
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Discard failed')
    }
  }

  async function handleOpenCommit() {
    try {
      const pre = await api.preCommit()
      setPreCommitData(pre)
      setShowCommitModal(true)
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Failed to check conflicts')
    }
  }

  async function handleCommit(resolutions: { make_n: string; model_n: string; year: number; keep: string }[]) {
    setCommitting(true)
    try {
      await api.commit(resolutions)
      setShowCommitModal(false)
      setStaging(null)
      api.wvCoverage().then(c => setCoverage(c)).catch(() => {})
      if (showVersions) api.versions(1).then(v => setVersions(v as unknown as { total: number; items: VersionRow[] })).catch(() => {})
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Commit failed')
    } finally { setCommitting(false) }
  }

  async function handleSaveEdit() {
    if (!editRow) return
    setSavingEdit(true)
    try {
      await api.patchStaging(editRow.id, editAh ? parseFloat(editAh) : null, editTech || null)
      setEditRow(null)
      loadStaging(stagingPage, stagingFilter)
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Save failed')
    } finally { setSavingEdit(false) }
  }

  async function handleSaveMasterEdit() {
    if (!editMasterRow) return
    setSavingMasterEdit(true)
    try {
      const res = await api.patchMaster(editMasterRow.id, {
        ah: editMasterAh ? parseFloat(editMasterAh) : null,
        technology: editMasterTech || null,
        battery_code: editMasterBc || null,
        scope: editMasterScope,
      })
      setMasterSaveResult(res.rows_updated)
      setMatchedLoading(true)
      try { setMatched(await api.wvMatched(matchedPage, 50, matchedSearch)) } catch {} finally { setMatchedLoading(false) }
      api.wvCoverage().then(c => setCoverage(c)).catch(() => {})
      if (editMasterScope === 'single') setEditMasterRow(null)
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Save failed')
    } finally { setSavingMasterEdit(false) }
  }

  async function handleDeleteMaster(row: MasterRecord) {
    if (!confirm(`Delete ${row.make_n} ${row.model_n} ${row.year} from master? This cannot be undone.`)) return
    setDeletingMasterId(row.id)
    try {
      await api.deleteMaster(row.id)
      setMatched(prev => prev ? { ...prev, total: prev.total - 1, items: prev.items.filter(r => r.id !== row.id) } : null)
      api.wvCoverage().then(c => setCoverage(c)).catch(() => {})
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Delete failed')
    } finally { setDeletingMasterId(null) }
  }

  const running = state?.status === 'running'
  const paused  = state?.status === 'paused'
  const active  = running || paused
  const pct     = state && state.total > 0 ? Math.round((state.processed / state.total) * 100) : 0

  const needsAttention = quotas.some(q => q.pct_used >= 100) || providers.some(p => !p.always_available && !p.configured)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      <div style={{ fontSize: '0.75rem', color: '#6b7280' }}>
        Searches the web to confirm battery specs for every vehicle combination in the database.
        Uses DuckDuckGo, Google CSE, and Tavily — results feed the master battery validation table.
      </div>

      {/* ── Coverage (first) ─────────────────────────────────────────────────── */}
      {coverageLoading ? (
        <div style={CARD}>
          <div style={{ fontSize: '0.75rem', color: '#6b7280', marginBottom: '0.75rem' }}>Coverage</div>
          <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap', alignItems: 'center' }}>
            {/* Donut skeleton */}
            <div style={{ width: 80, height: 80, borderRadius: '50%', background: 'linear-gradient(90deg, #f0f1f4 25%, #e4e5e9 50%, #f0f1f4 75%)', backgroundSize: '200% 100%', animation: 'shimmer 1.4s infinite', flexShrink: 0 }} />
            <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap' }}>
              {[80, 60, 70, 65, 55, 75].map((w, i) => (
                <div key={i} style={{ textAlign: 'center', minWidth: 70 }}>
                  <div style={{ height: 28, width: w, background: 'linear-gradient(90deg, #f0f1f4 25%, #e4e5e9 50%, #f0f1f4 75%)', backgroundSize: '200% 100%', animation: 'shimmer 1.4s infinite', borderRadius: 6, margin: '0 auto 6px' }} />
                  <div style={{ height: 10, width: 50, background: '#f0f1f4', borderRadius: 4, margin: '0 auto' }} />
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : coverage && (
        <div style={CARD}>
          <div style={{ fontSize: '0.75rem', color: '#6b7280', marginBottom: '0.75rem' }}>Coverage</div>
          {Number(coverage.unmatched) > 0 && (
            <div style={{
              display: 'flex', alignItems: 'flex-start', gap: '0.5rem',
              background: '#fff7ed', border: '1px solid #fed7aa',
              borderRadius: 8, padding: '0.55rem 0.75rem', marginBottom: '0.75rem',
              fontSize: '0.75rem', color: '#9a3412', lineHeight: 1.5,
            }}>
              <ExclamationTriangleIcon style={{ width: 14, height: 14, flexShrink: 0, marginTop: 1 }} />
              <span>
                <strong>{Number(coverage.unmatched).toLocaleString()} vehicle combinations</strong> in the
                vehicle years dataset still have no confirmed battery match. Run the pipeline to attempt
                resolution, or review unmatched entries below.
              </span>
            </div>
          )}
          <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap', alignItems: 'center' }}>
            <DonutChart pct={Number(coverage.pct_matched) || 0} />
            <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap' }}>
              {([
                ['Total Combos',   coverage.total,            '#6b7280'],
                ['Matched',        coverage.matched,          '#22c55e'],
                ['Unmatched',      coverage.unmatched,        R],
                ['Master Records', coverage.master_count,     '#6366f1'],
                ['In Staging',     coverage.staging_count,    '#f59e0b'],
                ['Buckets Left',   coverage.remaining_buckets,'#0ea5e9'],
              ] as [string, unknown, string][]).map(([label, val, color]) => (
                <div key={label} style={{ textAlign: 'center', minWidth: 70 }}>
                  <div style={{ fontSize: '1.4rem', fontWeight: 800, color }}>{String(val ?? '–')}</div>
                  <div style={{ fontSize: '0.68rem', color: '#9ca3af', marginTop: 2 }}>{label}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Run Controls ─────────────────────────────────────────────────────── */}
      <div style={CARD}>
        <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap', alignItems: 'flex-start' }}>

          {/* Providers — unified grid */}
          {providers.length > 0 && (
            <div>
              <div style={{ fontSize: '0.72rem', fontWeight: 700, color: '#9ca3af', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '0.55rem' }}>
                Providers for this run
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.65rem' }}>
                {providers.map(p => {
                  const isAlways = p.always_available
                  const isOn = isAlways || enabledProv.includes(p.provider)
                  const noKey = !isAlways && !p.configured
                  const canToggle = !isAlways && p.configured && !active

                  const bg = noKey ? '#f9fafb' : isOn ? '#f0fdf4' : '#fff5f5'
                  const border = noKey ? '#e2e4e9' : isOn ? '#bbf7d0' : '#fecaca'

                  return (
                    <div key={p.provider} style={{
                      display: 'flex', alignItems: 'center', gap: '0.65rem',
                      background: bg, border: `1px solid ${border}`,
                      borderRadius: 10, padding: '0.65rem 0.85rem',
                      opacity: noKey ? 0.55 : 1,
                    }}>
                      <GlobeAltIcon style={{ width: 13, height: 13, color: noKey ? '#9ca3af' : '#6b7280', flexShrink: 0 }} />
                      <span style={{ fontSize: '0.78rem', fontWeight: 600, color: noKey ? '#9ca3af' : 'rgba(17,24,39,0.8)', flex: 1, textTransform: 'capitalize' }}>
                        {p.provider}
                      </span>
                      {isAlways && (
                        <span style={{ fontSize: '0.62rem', fontWeight: 700, color: '#16a34a', background: '#dcfce7', borderRadius: 99, padding: '0.1rem 0.45rem', whiteSpace: 'nowrap' }}>
                          Always on
                        </span>
                      )}
                      {canToggle && (
                        <button
                          onClick={() => setEnabledProv(prev =>
                            prev.includes(p.provider)
                              ? prev.filter(x => x !== p.provider)
                              : [...prev, p.provider]
                          )}
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
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Right column: phase descriptions + dropdown + action buttons */}
          <div style={{ marginLeft: 'auto', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', gap: '0.75rem', minWidth: 210 }}>

            {/* Phase explanations */}
            <div>
              <div style={{ fontSize: '0.72rem', fontWeight: 700, color: '#9ca3af', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '0.55rem' }}>
                Pipeline Phases
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start' }}>
                  <span style={{ background: '#ede9fe', color: '#7c3aed', fontSize: '0.62rem', fontWeight: 700, borderRadius: 99, padding: '0.1rem 0.45rem', whiteSpace: 'nowrap', marginTop: 2, flexShrink: 0 }}>
                    Phase 1
                  </span>
                  <span style={{ fontSize: '0.73rem', color: '#6b7280', lineHeight: 1.45 }}>
                    Pre-fetches all vehicle + year buckets and stores raw search results in the local cache.
                  </span>
                </div>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start' }}>
                  <span style={{ background: '#dbeafe', color: '#1d4ed8', fontSize: '0.62rem', fontWeight: 700, borderRadius: 99, padding: '0.1rem 0.45rem', whiteSpace: 'nowrap', marginTop: 2, flexShrink: 0 }}>
                    Phase 2
                  </span>
                  <span style={{ fontSize: '0.73rem', color: '#6b7280', lineHeight: 1.45 }}>
                    Looks up battery specs per vehicle via enabled search providers. Writes confirmed results to staging.
                  </span>
                </div>
              </div>
            </div>

            {/* Bottom group: dropdown + buttons right-aligned */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', alignItems: 'flex-end' }}>
              <select value={phase} onChange={e => setPhase(e.target.value)} disabled={active}
                style={{ padding: '0.45rem 0.7rem', borderRadius: 8, border: '1px solid #e2e4e9', fontSize: '0.82rem', background: '#fff' }}>
                <option value="both">Both phases</option>
                <option value="phase1">Phase 1 only (prefetch)</option>
                <option value="phase2">Phase 2 only (lookup)</option>
              </select>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                {!active && (
                  <button onClick={handleRun}
                    style={{ ...btnStyle(R, '#fff'), animation: runPressed ? 'btn-press 0.28s ease' : 'none' }}>
                    <PlayIcon style={{ width: 15, height: 15 }} /> Run
                  </button>
                )}
                {running && (
                  <button onClick={() => api.wvPause()} style={btnStyle('#f59e0b', '#fff')}>
                    <PauseIcon style={{ width: 15, height: 15 }} /> Pause
                  </button>
                )}
                {paused && (
                  <button onClick={() => { api.wvResume(); startPolling() }} style={btnStyle('#22c55e', '#fff')}>
                    <PlayIcon style={{ width: 15, height: 15 }} /> Resume
                  </button>
                )}
                {active && (
                  <button onClick={() => api.wvCancel()} style={btnStyle('#fff', R, `1.5px solid ${R}`)}>
                    <XMarkIcon style={{ width: 15, height: 15 }} /> Cancel
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Progress */}
        {active && (
          <div style={{ marginTop: '1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#6b7280', marginBottom: 4 }}>
              <span>
                {state?.phase2_started_at
                  ? `Phase 2: ${state.processed} / ${state.total} vehicles · ${state.current_provider ?? ''}`
                  : `Phase 1: ${state?.phase1_processed ?? 0} / ${state?.phase1_total ?? '?'} buckets`
                }
              </span>
              <span style={{ fontWeight: 700 }}>{pct}%</span>
            </div>
            <div style={{ height: 7, background: '#e2e4e9', borderRadius: 99 }}>
              <div style={{ height: 7, borderRadius: 99, background: R, width: `${pct}%`, transition: 'width 0.4s' }} />
            </div>
            {state?.current_combo && (
              <div style={{ fontSize: '0.7rem', color: '#9ca3af', marginTop: 4, fontFamily: 'monospace' }}>{state.current_combo}</div>
            )}
          </div>
        )}

        {state && !active && state.status !== 'idle' && (
          <div style={{ marginTop: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <StatusBadge status={state.status} />
            {state.error_detail && <span style={{ fontSize: '0.78rem', color: R }}>{state.error_detail}</span>}
          </div>
        )}
      </div>

      {/* ── Logs ─────────────────────────────────────────────────────────────── */}
      {state && state.logs && state.logs.length > 0 && (
        <div style={CARD}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.65rem' }}>
            <div style={{ fontWeight: 700, fontSize: '0.85rem', color: '#374151' }}>Pipeline Logs</div>
            <span style={{ fontSize: '0.7rem', color: '#9ca3af' }}>{state.logs.length} entries</span>
          </div>
          <div ref={logRef} style={{
            background: '#f8f9fb', border: '1px solid #e2e4e9', borderRadius: 8,
            padding: '0.6rem 0.75rem', height: 260, overflowY: 'auto',
            fontSize: '0.71rem', fontFamily: "'Consolas', 'Courier New', monospace", lineHeight: 1.75,
          }}>
            {state.logs.map((entry, i) => {
              if (entry.level === 'milestone') {
                return (
                  <div key={i} style={{
                    background: '#eff6ff', border: '1px solid #bfdbfe', borderLeft: '3px solid #2563eb',
                    borderRadius: 6, padding: '0.35rem 0.6rem', margin: '0.5rem 0',
                    fontWeight: 700, color: '#1e40af',
                    display: 'flex', alignItems: 'center', gap: '0.4rem',
                  }}>
                    <span>📊</span>
                    <span style={{ flex: 1 }}>{entry.message}</span>
                    <span style={{ fontSize: '0.62rem', color: '#93c5fd', fontWeight: 400 }}>{new Date(entry.ts).toLocaleTimeString()}</span>
                  </div>
                )
              }
              const color = entry.level === 'success' ? '#15803d' : entry.level === 'error' ? '#dc2626' : entry.level === 'warn' ? '#b45309' : '#374151'
              const prefix = entry.level === 'success' ? '✓ ' : entry.level === 'error' ? '✗ ' : entry.level === 'warn' ? '⚠ ' : ''
              return (
                <div key={i} style={{
                  color, borderBottom: i < state.logs.length - 1 ? '1px solid #f1f3f5' : 'none',
                  paddingBottom: '0.1rem', display: 'flex', justifyContent: 'space-between', gap: '0.5rem',
                }}>
                  <span>{prefix}{entry.message}</span>
                  <span style={{ color: '#9ca3af', fontSize: '0.62rem', flexShrink: 0 }}>{new Date(entry.ts).toLocaleTimeString()}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── Quotas + Version History (side by side) ──────────────────────────── */}
      <div style={{ display: 'flex', gap: '1.25rem', alignItems: 'flex-start' }}>

        {/* API Quotas — compact horizontal boxes */}
        {quotas.length > 0 && (
          <div style={{ ...CARD, flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: '0.72rem', color: '#9ca3af', marginBottom: '0.65rem', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
              API Quotas
            </div>
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              {quotas.map(q => {
                const unlimited = q.quota_limit === -1
                const pctQ = Math.min(q.pct_used, 100)
                const barColor = pctQ > 90 ? R : pctQ > 70 ? '#f59e0b' : '#22c55e'
                return (
                  <div key={q.provider} style={{
                    background: '#fff', border: '1px solid #e2e4e9',
                    borderRadius: 7, padding: '0.4rem 0.6rem', minWidth: 110,
                    boxShadow: '0 2px 6px rgba(0,0,0,0.07)',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.3rem' }}>
                      <span style={{ fontSize: '0.72rem', fontWeight: 600, color: '#111827', textTransform: 'capitalize' }}>
                        {q.provider}
                      </span>
                      <span style={{ fontSize: '0.65rem', color: unlimited ? '#22c55e' : pctQ > 90 ? R : '#6b7280', fontWeight: 600 }}>
                        {unlimited ? '∞' : `${pctQ.toFixed(0)}%`}
                      </span>
                    </div>
                    <div style={{ height: 3, background: '#e2e4e9', borderRadius: 99, marginBottom: '0.25rem' }}>
                      <div style={{
                        height: 3, borderRadius: 99,
                        background: unlimited ? '#22c55e' : barColor,
                        width: unlimited ? '100%' : `${pctQ}%`,
                        transition: 'width 0.4s',
                      }} />
                    </div>
                    <div style={{ fontSize: '0.65rem', color: '#6b7280', fontWeight: 500 }}>
                      {unlimited
                        ? `${q.calls_made.toLocaleString()} calls`
                        : `${q.calls_made.toLocaleString()} / ${q.quota_limit.toLocaleString()}`
                      }
                    </div>
                    {q.period_end && (
                      <div style={{
                        fontSize: '0.6rem', marginTop: '0.2rem', fontWeight: 500,
                        color: (q.days_until_reset ?? 30) < 3 ? '#dc2626' : (q.days_until_reset ?? 30) < 7 ? '#b45309' : '#9ca3af',
                      }}>
                        Resets{q.days_until_reset != null ? ` in ${q.days_until_reset}d` : ''} · {new Date(q.period_end).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
            {needsAttention && (
              <div style={{
                display: 'flex', alignItems: 'flex-start', gap: '0.5rem',
                marginTop: '0.75rem', padding: '0.5rem 0.75rem',
                background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 8,
                fontSize: '0.73rem', color: '#92400e',
              }}>
                <ExclamationTriangleIcon style={{ width: 14, height: 14, flexShrink: 0, marginTop: 1 }} />
                One or more providers are at their limit or not configured. Contact IT to renew or set up API keys.
              </div>
            )}
          </div>
        )}

        {/* Version History */}
        <div style={{ ...CARD, flex: 1, minWidth: 0 }}>
          <button onClick={async () => {
            const next = !showVersions; setShowVersions(next)
            if (next) {
              const v = await api.versions(1) as unknown as { total: number; items: VersionRow[] }
              setVersions(v)
            }
          }} style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.85rem', color: '#374151', padding: 0 }}>
            {showVersions
              ? <ChevronDownIcon style={{ width: 16, height: 16 }} />
              : <ChevronRightIcon style={{ width: 16, height: 16 }} />
            }
            Version History {versions ? `(${versions.total})` : ''}
          </button>
          {showVersions && versions && (
            <div style={{ marginTop: '0.75rem', overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.75rem' }}>
                <thead>
                  <tr style={{ background: '#f8f9fb' }}>
                    {['#', 'Committed At', 'By', 'Added', 'Removed', 'Conflicts', ''].map(h => (
                      <th key={h} style={{ padding: '0.4rem 0.6rem', textAlign: 'left', fontWeight: 500, color: '#6b7280', borderBottom: '1px solid #e2e4e9' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {versions.items.map((v, i) => (
                    <tr key={v.id} style={{ background: i % 2 === 0 ? '#fff' : '#f9fafb', borderBottom: '1px solid #e2e4e9' }}>
                      <td style={{ padding: '0.35rem 0.6rem', fontWeight: 500 }}>#{v.version_number}</td>
                      <td style={{ padding: '0.35rem 0.6rem', color: '#6b7280' }}>{new Date(v.committed_at).toLocaleString()}</td>
                      <td style={{ padding: '0.35rem 0.6rem' }}>{v.committed_by}</td>
                      <td style={{ padding: '0.35rem 0.6rem', color: '#15803d' }}>{v.committed_count}</td>
                      <td style={{ padding: '0.35rem 0.6rem', color: R }}>{v.removed_count}</td>
                      <td style={{ padding: '0.35rem 0.6rem', color: '#f59e0b' }}>{v.conflict_count}</td>
                      <td style={{ padding: '0.35rem 0.6rem' }}>
                        <button onClick={async () => {
                          if (!confirm(`Revert version #${v.version_number}? This cannot be undone.`)) return
                          try {
                            await api.revert(v.id)
                            const vers = await api.versions(1) as unknown as { total: number; items: VersionRow[] }
                            setVersions(vers)
                            api.wvCoverage().then(c => setCoverage(c)).catch(() => {})
                          } catch (err: unknown) {
                            alert(err instanceof Error ? err.message : 'Revert failed')
                          }
                        }} style={{
                          display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
                          fontSize: '0.72rem', color: R, background: '#fff5f5',
                          border: '1px solid #fecaca', borderRadius: 6,
                          padding: '0.2rem 0.5rem', cursor: 'pointer',
                        }}>
                          <ArrowUturnLeftIcon style={{ width: 12, height: 12 }} />
                          Revert
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* ── Staging area ─────────────────────────────────────────────────────── */}
      {staging && staging.has_staging && (
        <div style={{ ...CARD, border: '1.5px solid #fde68a', background: '#fffbeb' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem', flexWrap: 'wrap', gap: '0.5rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <span style={{ fontWeight: 700, fontSize: '0.88rem', color: '#92400e' }}>Staging Area</span>
              <span style={{ background: '#f59e0b', color: '#fff', fontSize: '0.7rem', fontWeight: 700, padding: '0.15rem 0.5rem', borderRadius: 20 }}>
                {staging.total} rows
              </span>
            </div>
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <button onClick={handleFixAh} disabled={fixingAh} style={btnStyle('#6366f1', '#fff')}>
                <BoltIcon style={{ width: 14, height: 14 }} />
                {fixingAh ? 'Fixing…' : 'Fix Suspicious Ah'}
              </button>
              <button onClick={handleDiscard} style={btnStyle('#fff', R, `1.5px solid ${R}`)}>
                <TrashIcon style={{ width: 14, height: 14 }} />
                Discard All
              </button>
              <button onClick={handleOpenCommit} style={btnStyle(R, '#fff')}>
                <ArrowUpTrayIcon style={{ width: 14, height: 14 }} />
                Review & Commit
              </button>
            </div>
          </div>

          {fixResult && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.78rem', color: '#6366f1', background: '#ede9fe', borderRadius: 8, padding: '0.45rem 0.75rem', marginBottom: '0.5rem' }}>
              <CheckCircleIcon style={{ width: 14, height: 14 }} />
              Fixed {fixResult.fixed} rows · {fixResult.unchanged} unchanged · {fixResult.failed} failed
            </div>
          )}

          {/* Filter tabs */}
          <div style={{ display: 'flex', gap: '0.35rem', marginBottom: '0.75rem', borderBottom: '1px solid #fde68a', paddingBottom: '0.5rem' }}>
            {([
              ['all',       `All (${staging.total})`],
              ['valid',     `Valid (${staging.valid_count})`],
              ['invalid',   `Invalid (${staging.invalid_count})`],
              ['conflicts', `Conflicts (${staging.conflict_count})`],
            ] as [string, string][]).map(([f, label]) => (
              <button key={f} onClick={async () => {
                setStagingFilter(f); setStagingPage(1)
                const s = await api.staging(1, f) as unknown as StagingResp
                setStaging(s)
              }} style={{
                background: stagingFilter === f ? '#f59e0b' : 'transparent',
                color:      stagingFilter === f ? '#fff'    : '#92400e',
                border: 'none', borderRadius: 8, padding: '0.25rem 0.65rem',
                fontSize: '0.75rem', fontWeight: 600, cursor: 'pointer',
              }}>
                {label}
              </button>
            ))}
          </div>

          {/* Table */}
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.75rem' }}>
              <thead>
                <tr style={{ background: '#fef3c7' }}>
                  {['Make', 'Model', 'Year', 'Ah', 'Tech', 'Source', 'Valid', 'Conflict', ''].map(h => (
                    <th key={h} style={{ padding: '0.4rem 0.6rem', textAlign: 'left', fontWeight: 700, color: '#92400e', borderBottom: '1px solid #fde68a' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {staging.items.map((row, i) => (
                  <tr key={row.id} style={{ background: !row.is_valid ? '#fff5f5' : row.conflict ? '#fffbeb' : i % 2 === 0 ? '#fff' : '#fafafa', borderBottom: '1px solid #fde68a' }}>
                    <td style={{ padding: '0.35rem 0.6rem' }}>{row.make_n}</td>
                    <td style={{ padding: '0.35rem 0.6rem' }}>{row.model_n}</td>
                    <td style={{ padding: '0.35rem 0.6rem' }}>{row.year}</td>
                    <td style={{ padding: '0.35rem 0.6rem', fontWeight: 700 }}>{row.ah ?? '–'}</td>
                    <td style={{ padding: '0.35rem 0.6rem' }}>
                      <span style={{ background: '#e0e7ff', color: '#3730a3', padding: '0.1rem 0.4rem', borderRadius: 6, fontSize: '0.68rem', fontWeight: 700 }}>
                        {row.technology ?? 'MF'}
                      </span>
                    </td>
                    <td style={{ padding: '0.35rem 0.6rem', color: '#6b7280' }}>{row.source ?? '–'}</td>
                    <td style={{ padding: '0.35rem 0.6rem' }}>
                      {row.is_valid
                        ? <CheckCircleIcon style={{ width: 16, height: 16, color: '#16a34a' }} />
                        : <XCircleIcon style={{ width: 16, height: 16, color: R }} title={row.invalid_reason ?? ''} />
                      }
                    </td>
                    <td style={{ padding: '0.35rem 0.6rem' }}>
                      {row.conflict && <ExclamationTriangleIcon style={{ width: 16, height: 16, color: '#f59e0b' }} />}
                    </td>
                    <td style={{ padding: '0.35rem 0.6rem' }}>
                      <button onClick={() => { setEditRow(row); setEditAh(String(row.ah ?? '')); setEditTech(row.technology ?? 'MF') }}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '0.15rem', color: '#6b7280', display: 'flex' }}>
                        <PencilSquareIcon style={{ width: 16, height: 16 }} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginTop: '0.75rem', justifyContent: 'flex-end' }}>
            <button disabled={stagingPage === 1} onClick={async () => {
              const p = stagingPage - 1; setStagingPage(p)
              const s = await api.staging(p, stagingFilter) as unknown as StagingResp; setStaging(s)
            }} style={paginationBtn(stagingPage === 1)}>← Prev</button>
            <span style={{ fontSize: '0.75rem', color: '#6b7280' }}>
              Page {stagingPage} / {Math.ceil((staging.total || 1) / 50)}
            </span>
            <button disabled={stagingPage * 50 >= staging.total} onClick={async () => {
              const p = stagingPage + 1; setStagingPage(p)
              const s = await api.staging(p, stagingFilter) as unknown as StagingResp; setStaging(s)
            }} style={paginationBtn(stagingPage * 50 >= staging.total)}>Next →</button>
          </div>
        </div>
      )}

      {/* ── Matched Vehicles ──────────────────────────────────────────────────── */}
      <div style={CARD}>
        <button onClick={async () => {
          const next = !showMatched; setShowMatched(next)
          if (next && !matched) {
            setMatchedLoading(true)
            try { setMatched(await api.wvMatched(1, 50, '') as unknown as MatchedResp) } catch {} finally { setMatchedLoading(false) }
          }
        }} style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.85rem', color: '#374151', padding: 0, width: '100%' }}>
          {showMatched ? <ChevronDownIcon style={{ width: 16, height: 16 }} /> : <ChevronRightIcon style={{ width: 16, height: 16 }} />}
          <GlobeAltIcon style={{ width: 15, height: 15, color: '#22c55e' }} />
          <span style={{ fontWeight: 700 }}>Matched Vehicles</span>
          {matched && <span style={{ fontSize: '0.72rem', color: '#6b7280', marginLeft: '0.25rem' }}>({matched.total.toLocaleString()} records)</span>}
        </button>
        {showMatched && (
          <div style={{ marginTop: '0.75rem' }}>
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.65rem' }}>
              <input
                placeholder="Search make, model…"
                value={matchedSearch}
                onChange={async e => {
                  const q = e.target.value; setMatchedSearch(q); setMatchedPage(1)
                  setMatchedLoading(true)
                  try { setMatched(await api.wvMatched(1, 50, q) as unknown as MatchedResp) } catch {} finally { setMatchedLoading(false) }
                }}
                style={{ flex: 1, padding: '0.4rem 0.65rem', borderRadius: 7, border: '1px solid #d1d5db', fontSize: '0.8rem' }}
              />
            </div>
            {matchedLoading ? (
              <div style={{ textAlign: 'center', padding: '1.5rem', color: '#9ca3af', fontSize: '0.8rem' }}>Loading…</div>
            ) : matched && matched.items.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '1.5rem', color: '#9ca3af', fontSize: '0.8rem' }}>No matched records yet. Run Phase 2 and commit staging to populate.</div>
            ) : matched && (
              <>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
                    <thead>
                      <tr style={{ background: '#f8f9fb' }}>
                        {['Make', 'Model', 'Year', 'Battery Code', 'Ah', 'Technology', 'Source', 'Validated', ''].map(h => (
                          <th key={h} style={{ padding: '0.45rem 0.6rem', textAlign: 'left', fontWeight: 600, color: '#374151', borderBottom: '1px solid #e2e4e9', whiteSpace: 'nowrap' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {matched.items.map((row) => {
                        const src = row.source ?? ''
                        const srcColor = src === 'brave' ? '#b45309' : src === 'tavily' ? '#4f46e5' : src === 'duckduckgo' ? '#2563eb' : src === 'carquery' ? '#15803d' : '#6b7280'
                        const srcBg = src === 'brave' ? '#fef3c7' : src === 'tavily' ? '#ede9fe' : src === 'duckduckgo' ? '#dbeafe' : src === 'carquery' ? '#dcfce7' : '#f3f4f6'
                        return (
                          <tr key={row.id} style={{ borderBottom: '1px solid #f1f3f5' }}>
                            <td style={{ padding: '0.4rem 0.6rem', color: '#111827' }}>{row.make_n}</td>
                            <td style={{ padding: '0.4rem 0.6rem', color: '#111827' }}>{row.model_n}</td>
                            <td style={{ padding: '0.4rem 0.6rem', color: '#374151' }}>{row.year}</td>
                            <td style={{ padding: '0.4rem 0.6rem', color: '#374151', fontFamily: 'monospace', fontSize: '0.73rem' }}>{row.battery_code ?? '—'}</td>
                            <td style={{ padding: '0.4rem 0.6rem', color: '#374151' }}>{row.ah != null ? `${row.ah} Ah` : '—'}</td>
                            <td style={{ padding: '0.4rem 0.6rem', color: '#374151' }}>{row.technology ?? '—'}</td>
                            <td style={{ padding: '0.4rem 0.6rem' }}>
                              <span style={{ background: srcBg, color: srcColor, borderRadius: 99, padding: '0.15rem 0.5rem', fontSize: '0.68rem', fontWeight: 600, textTransform: 'capitalize' }}>{src || '—'}</span>
                            </td>
                            <td style={{ padding: '0.4rem 0.6rem', color: '#9ca3af', fontSize: '0.72rem' }}>
                              {row.validated_at ? new Date(row.validated_at).toLocaleDateString() : '—'}
                            </td>
                            <td style={{ padding: '0.4rem 0.6rem' }}>
                              <div style={{ display: 'flex', gap: '0.2rem' }}>
                                <button
                                  onClick={() => { setEditMasterRow(row); setEditMasterAh(String(row.ah ?? '')); setEditMasterTech(row.technology ?? 'MF'); setEditMasterBc(row.battery_code ?? ''); setEditMasterScope('single'); setMasterSaveResult(null) }}
                                  title="Edit"
                                  style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '0.15rem', color: '#6b7280', display: 'flex' }}>
                                  <PencilSquareIcon style={{ width: 15, height: 15 }} />
                                </button>
                                <button
                                  onClick={() => handleDeleteMaster(row)}
                                  disabled={deletingMasterId === row.id}
                                  title="Delete"
                                  style={{ background: 'none', border: 'none', cursor: deletingMasterId === row.id ? 'not-allowed' : 'pointer', padding: '0.15rem', color: deletingMasterId === row.id ? '#9ca3af' : R, display: 'flex' }}>
                                  <TrashIcon style={{ width: 15, height: 15 }} />
                                </button>
                              </div>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginTop: '0.65rem', justifyContent: 'flex-end' }}>
                  <button disabled={matchedPage === 1} onClick={async () => {
                    const p = matchedPage - 1; setMatchedPage(p); setMatchedLoading(true)
                    try { setMatched(await api.wvMatched(p, 50, matchedSearch) as unknown as MatchedResp) } catch {} finally { setMatchedLoading(false) }
                  }} style={paginationBtn(matchedPage === 1)}>← Prev</button>
                  <span style={{ fontSize: '0.75rem', color: '#6b7280' }}>Page {matchedPage} / {Math.ceil((matched.total || 1) / 50)}</span>
                  <button disabled={matchedPage * 50 >= matched.total} onClick={async () => {
                    const p = matchedPage + 1; setMatchedPage(p); setMatchedLoading(true)
                    try { setMatched(await api.wvMatched(p, 50, matchedSearch) as unknown as MatchedResp) } catch {} finally { setMatchedLoading(false) }
                  }} style={paginationBtn(matchedPage * 50 >= matched.total)}>Next →</button>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* ── Sessions ─────────────────────────────────────────────────────────── */}
      <div style={CARD}>
        <button onClick={async () => {
          const next = !showSessions; setShowSessions(next)
          if (next) api.sessions().then(setSessions).catch(() => {})
        }} style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.85rem', color: '#374151', padding: 0, width: '100%' }}>
          {showSessions ? <ChevronDownIcon style={{ width: 16, height: 16 }} /> : <ChevronRightIcon style={{ width: 16, height: 16 }} />}
          <span style={{ fontWeight: 700 }}>Active Sessions</span>
          {sessions.length > 0 && <span style={{ fontSize: '0.72rem', color: '#6b7280', marginLeft: '0.25rem' }}>({sessions.length})</span>}
        </button>
        {showSessions && (
          <div style={{ marginTop: '0.75rem' }}>
            {sessions.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '1rem', color: '#9ca3af', fontSize: '0.8rem' }}>No active sessions found.</div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
                <thead>
                  <tr style={{ background: '#f8f9fb' }}>
                    {['Created', 'Expires', 'IP Address', '', ''].map((h, i) => (
                      <th key={i} style={{ padding: '0.45rem 0.6rem', textAlign: 'left', fontWeight: 600, color: '#374151', borderBottom: '1px solid #e2e4e9' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sessions.map(s => (
                    <tr key={s.id} style={{ borderBottom: '1px solid #f1f3f5' }}>
                      <td style={{ padding: '0.4rem 0.6rem', color: '#374151' }}>{new Date(s.created_at).toLocaleString()}</td>
                      <td style={{ padding: '0.4rem 0.6rem', color: '#374151' }}>{new Date(s.expires_at).toLocaleString()}</td>
                      <td style={{ padding: '0.4rem 0.6rem', color: '#9ca3af', fontFamily: 'monospace' }}>{s.ip_address ?? '—'}</td>
                      <td style={{ padding: '0.4rem 0.6rem' }}>
                        {s.is_current && (
                          <span style={{ background: '#dcfce7', color: '#15803d', borderRadius: 99, padding: '0.15rem 0.5rem', fontSize: '0.68rem', fontWeight: 600 }}>Current</span>
                        )}
                      </td>
                      <td style={{ padding: '0.4rem 0.6rem', textAlign: 'right' }}>
                        <button
                          disabled={s.is_current || revokingId === s.id}
                          onClick={async () => {
                            if (!confirm('Revoke this session?')) return
                            setRevokingId(s.id)
                            try {
                              await api.revokeSession(s.id)
                              setSessions(prev => prev.filter(x => x.id !== s.id))
                            } catch (err: unknown) {
                              alert(err instanceof Error ? err.message : 'Revoke failed')
                            } finally { setRevokingId(null) }
                          }}
                          style={{
                            background: s.is_current ? '#f3f4f6' : '#fee2e2',
                            color: s.is_current ? '#9ca3af' : '#dc2626',
                            border: 'none', borderRadius: 6, padding: '0.25rem 0.6rem',
                            fontSize: '0.72rem', fontWeight: 600, cursor: s.is_current ? 'not-allowed' : 'pointer',
                          }}
                        >
                          {revokingId === s.id ? '…' : s.is_current ? 'Use Logout' : 'Revoke'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>

      {/* ── Edit row modal ─────────────────────────────────────────────────────── */}
      {editRow && (
        <Modal title={`Edit: ${editRow.make_n} ${editRow.model_n} ${editRow.year}`} onClose={() => setEditRow(null)}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div>
              <label style={{ fontSize: '0.78rem', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '0.3rem' }}>Ah Capacity</label>
              <input type="number" value={editAh} onChange={e => setEditAh(e.target.value)} min={20} max={250}
                style={{ width: '100%', padding: '0.5rem', borderRadius: 8, border: '1px solid #d1d5db', fontSize: '0.9rem' }} />
            </div>
            <div>
              <label style={{ fontSize: '0.78rem', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '0.3rem' }}>Technology</label>
              <select value={editTech} onChange={e => setEditTech(e.target.value)}
                style={{ width: '100%', padding: '0.5rem', borderRadius: 8, border: '1px solid #d1d5db', fontSize: '0.9rem' }}>
                {['MF', 'AGM', 'EFB', 'GEL', 'WET'].map(t => <option key={t}>{t}</option>)}
              </select>
            </div>
            <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
              <button onClick={() => setEditRow(null)} style={btnStyle('#f3f4f6', '#374151')}>Cancel</button>
              <button onClick={handleSaveEdit} disabled={savingEdit} style={btnStyle(R, '#fff')}>
                {savingEdit ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* ── Commit modal ─────────────────────────────────────────────────────── */}
      {showCommitModal && preCommitData && (
        <CommitModal
          preCommit={preCommitData}
          committing={committing}
          onCancel={() => setShowCommitModal(false)}
          onCommit={handleCommit}
        />
      )}

      {/* ── Edit master record modal ──────────────────────────────────────────── */}
      {editMasterRow && (
        <Modal title={`${editMasterRow.make_n} ${editMasterRow.model_n} ${editMasterRow.year}`} onClose={() => setEditMasterRow(null)}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {/* Scope selector */}
            <div style={{ background: '#f8f9fb', border: '1px solid #e2e4e9', borderRadius: 10, padding: '0.65rem 0.75rem' }}>
              <div style={{ fontSize: '0.68rem', fontWeight: 700, color: '#9ca3af', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '0.45rem' }}>Update scope</div>
              {(['single', 'bucket'] as const).map(s => {
                const bs = Math.floor(editMasterRow.year / 5) * 5
                const label = s === 'single' ? `This year only (${editMasterRow.year})` : `All ${bs}–${bs + 4} bucket records`
                return (
                  <label key={s} style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', fontSize: '0.8rem', color: '#374151', cursor: 'pointer', padding: '0.2rem 0' }}>
                    <input type="radio" name="masterScope" value={s} checked={editMasterScope === s}
                      onChange={() => { setEditMasterScope(s); setMasterSaveResult(null) }}
                      style={{ accentColor: R, width: 14, height: 14, flexShrink: 0 }} />
                    <span style={{ fontWeight: editMasterScope === s ? 600 : 400 }}>{label}</span>
                    {s === 'bucket' && <span style={{ background: '#fef3c7', color: '#92400e', fontSize: '0.58rem', fontWeight: 700, borderRadius: 99, padding: '0.1rem 0.35rem' }}>Bulk</span>}
                  </label>
                )
              })}
            </div>
            <div>
              <label style={{ fontSize: '0.78rem', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '0.3rem' }}>Battery Code</label>
              <input value={editMasterBc} onChange={e => setEditMasterBc(e.target.value)} placeholder="e.g. NS60L"
                style={{ width: '100%', padding: '0.5rem', borderRadius: 8, border: '1px solid #d1d5db', fontSize: '0.9rem', fontFamily: 'monospace', boxSizing: 'border-box' }} />
            </div>
            <div>
              <label style={{ fontSize: '0.78rem', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '0.3rem' }}>Ah Capacity</label>
              <input type="number" value={editMasterAh} onChange={e => setEditMasterAh(e.target.value)} min={20} max={250}
                style={{ width: '100%', padding: '0.5rem', borderRadius: 8, border: '1px solid #d1d5db', fontSize: '0.9rem', boxSizing: 'border-box' }} />
            </div>
            <div>
              <label style={{ fontSize: '0.78rem', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '0.3rem' }}>Technology</label>
              <select value={editMasterTech} onChange={e => setEditMasterTech(e.target.value)}
                style={{ width: '100%', padding: '0.5rem', borderRadius: 8, border: '1px solid #d1d5db', fontSize: '0.9rem', boxSizing: 'border-box' }}>
                {['MF', 'AGM', 'EFB', 'GEL', 'WET'].map(t => <option key={t}>{t}</option>)}
              </select>
            </div>
            {masterSaveResult !== null && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', background: '#dcfce7', border: '1px solid #bbf7d0', borderRadius: 8, padding: '0.5rem 0.75rem', fontSize: '0.78rem', color: '#15803d' }}>
                <CheckCircleIcon style={{ width: 14, height: 14 }} />
                Updated {masterSaveResult} record{masterSaveResult !== 1 ? 's' : ''}
              </div>
            )}
            <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
              <button onClick={() => setEditMasterRow(null)} style={btnStyle('#f3f4f6', '#374151')}>{masterSaveResult !== null ? 'Close' : 'Cancel'}</button>
              {masterSaveResult === null && (
                <button onClick={handleSaveMasterEdit} disabled={savingMasterEdit} style={btnStyle(R, '#fff')}>
                  {savingMasterEdit ? 'Saving…' : editMasterScope === 'bucket' ? 'Update bucket' : 'Save'}
                </button>
              )}
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}

// ── Commit modal ──────────────────────────────────────────────────────────────

function CommitModal({ preCommit, committing, onCancel, onCommit }: {
  preCommit: { conflict_count: number; conflicts: unknown[] }
  committing: boolean
  onCancel: () => void
  onCommit: (r: { make_n: string; model_n: string; year: number; keep: string }[]) => void
}) {
  const [resolutions, setResolutions] = useState<Record<string, string>>({})
  function key(c: unknown) {
    const conflict = c as { make_n: string; model_n: string; year: number }
    return `${conflict.make_n}|${conflict.model_n}|${conflict.year}`
  }
  return (
    <Modal title="Review & Commit" onClose={onCancel}>
      {preCommit.conflict_count > 0 ? (
        <div style={{ marginBottom: '0.75rem' }}>
          <p style={{ fontSize: '0.82rem', color: '#92400e', marginBottom: '0.5rem' }}>
            {preCommit.conflict_count} conflict{preCommit.conflict_count > 1 ? 's' : ''} — choose which version to keep:
          </p>
          {preCommit.conflicts.map((c: unknown) => {
            const conflict = c as { make_n: string; model_n: string; year: number; conflict_detail: { current: { ah: unknown; technology: unknown }; staged: { ah: unknown; technology: unknown } } }
            const k = key(c)
            return (
              <div key={k} style={{ background: '#fef3c7', borderRadius: 8, padding: '0.6rem', marginBottom: '0.4rem', fontSize: '0.78rem' }}>
                <strong>{conflict.make_n} {conflict.model_n} {conflict.year}</strong>
                <div style={{ display: 'flex', gap: '1rem', marginTop: '0.35rem' }}>
                  {(['staging', 'current'] as const).map(opt => (
                    <label key={opt} style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', cursor: 'pointer' }}>
                      <input type="radio" name={k} value={opt} checked={(resolutions[k] || 'staging') === opt}
                        onChange={() => setResolutions(prev => ({ ...prev, [k]: opt }))}
                        style={{ accentColor: R }} />
                      {opt === 'staging'
                        ? `New: ${conflict.conflict_detail?.staged?.ah} Ah / ${conflict.conflict_detail?.staged?.technology}`
                        : `Keep current: ${conflict.conflict_detail?.current?.ah} Ah / ${conflict.conflict_detail?.current?.technology}`
                      }
                    </label>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <p style={{ fontSize: '0.82rem', color: '#374151', marginBottom: '0.75rem' }}>No conflicts. Ready to commit all staged rows.</p>
      )}
      <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
        <button onClick={onCancel} style={btnStyle('#f3f4f6', '#374151')}>Cancel</button>
        <button onClick={() => {
          const res = preCommit.conflicts.map((c: unknown) => {
            const conflict = c as { make_n: string; model_n: string; year: number }
            return { make_n: conflict.make_n, model_n: conflict.model_n, year: conflict.year, keep: resolutions[key(c)] || 'staging' }
          })
          onCommit(res)
        }} disabled={committing} style={btnStyle(R, '#fff')}>
          <ArrowUpTrayIcon style={{ width: 14, height: 14 }} />
          {committing ? 'Committing…' : 'Commit to Master'}
        </button>
      </div>
    </Modal>
  )
}

// ── Shared sub-components ─────────────────────────────────────────────────────

function DonutChart({ pct }: { pct: number }) {
  const r = 45, stroke = 15
  const circum = 2 * Math.PI * r
  const arc    = (pct / 100) * circum
  return (
    <svg width={110} height={110} viewBox="0 0 110 110">
      <circle cx={55} cy={55} r={r} fill="none" stroke="#e2e4e9" strokeWidth={stroke} />
      <circle cx={55} cy={55} r={r} fill="none"
        stroke={pct > 80 ? '#22c55e' : pct > 50 ? '#f59e0b' : R}
        strokeWidth={stroke}
        strokeDasharray={`${arc} ${circum - arc}`}
        strokeLinecap="round"
        transform="rotate(-90 55 55)"
        style={{ transition: 'stroke-dasharray 0.6s ease' }}
      />
      <text x={55} y={51} textAnchor="middle" fontWeight={800} fontSize={17} fill="#111827">{pct.toFixed(1)}%</text>
      <text x={55} y={64} textAnchor="middle" fontSize={8.5} fill="#6b7280" letterSpacing="0.08em">COVERED</text>
    </svg>
  )
}

function StatusBadge({ status }: { status: PipelineStatus }) {
  const map: Record<PipelineStatus, [string, string]> = {
    idle:      ['#6b7280', '#f3f4f6'],
    running:   [R,         '#fff5f5'],
    paused:    ['#92400e', '#fef3c7'],
    done:      ['#15803d', '#dcfce7'],
    error:     [R,         '#fff5f5'],
    cancelled: ['#92400e', '#fef3c7'],
  }
  const [color, bg] = map[status] ?? ['#6b7280', '#f3f4f6']
  return (
    <span style={{ fontSize: '0.72rem', fontWeight: 700, padding: '0.2rem 0.6rem', borderRadius: 20, background: bg, color, textTransform: 'capitalize' }}>
      {status}
    </span>
  )
}

function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', zIndex: 200,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem',
    }} onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div style={{
        background: '#fff', borderRadius: 16, border: '1px solid #e2e4e9',
        boxShadow: '0 8px 40px rgba(0,0,0,0.18)',
        padding: '1.5rem', width: '100%', maxWidth: 480, maxHeight: '85vh', overflowY: 'auto',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h3 style={{ fontWeight: 800, fontSize: '1rem', color: '#111827', margin: 0 }}>{title}</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280', display: 'flex', padding: '0.2rem' }}>
            <XMarkIcon style={{ width: 20, height: 20 }} />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

function btnStyle(bg: string, color: string, border?: string): React.CSSProperties {
  return {
    display: 'inline-flex', alignItems: 'center', gap: '0.35rem',
    background: bg, color, border: border ?? 'none', borderRadius: 8,
    padding: '0.45rem 1rem', fontWeight: 700, fontSize: '0.82rem', cursor: 'pointer',
    whiteSpace: 'nowrap',
  }
}

function paginationBtn(disabled: boolean): React.CSSProperties {
  return {
    background: '#f3f4f6', border: '1px solid #e2e4e9', borderRadius: 8,
    padding: '0.3rem 0.65rem', fontSize: '0.75rem', cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.4 : 1, color: '#374151', fontWeight: 600,
  }
}
