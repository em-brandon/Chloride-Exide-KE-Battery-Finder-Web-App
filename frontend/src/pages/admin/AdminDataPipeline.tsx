import { useState, useRef, useEffect, useCallback } from 'react'
import chlorideExideLogo from '@/assets/chlorideexidebrandlogo.webp'
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
  PencilIcon,
  WrenchScrewdriverIcon,
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
  fixStagingAh,
  patchStagingRow,
  patchMasterRecord,
  deleteMasterRecord,
  crspUpload,
  type MasterRecordPatch,
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
  // CRSP pipeline
  runCrspPipeline,
  getCrspStatus,
  pauseCrsp,
  resumeCrsp,
  cancelCrsp,
  getCrspStaging,
  patchCrspStagingRow,
  crspPreCommit,
  commitCrspStaging,
  discardCrspStaging,
  getCrspVersions,
  getCrspVersionChangelog,
  revertCrspVersion,
  getCrspStats,
  getCrspCacheStatus,
  refreshCrspCache,
  type CrspStatus,
  type CrspStagingResponse,
  type CrspConflictResolution,
  type CrspCommitResult,
  type CrspVersionsResponse,
  type CrspChangelogResponse,
  type CrspStats,
  type CrspCacheStatus,
} from '@/lib/adminApi'

// ── Design tokens ─────────────────────────────────────────────────────────────
const R  = '#CC0000'
const RD = '#990000'
const CARD: React.CSSProperties = {
  background: 'var(--adm-card-bg)',
  borderRadius: '14px',
  border: '1px solid var(--adm-card-border)',
  boxShadow: 'var(--adm-card-shadow)',
  fontFamily: "'Segoe UI', system-ui, sans-serif",
}

// ── Types ─────────────────────────────────────────────────────────────────────
type StageStatus = 'idle' | 'ready' | 'running' | 'done' | 'error'
type DatasetTab  = 'crsp' | 'webvalidate'

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
    description: 'Check that required columns (make, model, engine_capacity, fuel) are present and non-empty.',
    icon: <DocumentMagnifyingGlassIcon style={{ width: 16, height: 16 }} />,
  },
  {
    id: 'normalize',
    label: 'Normalize Fields',
    description: 'Uppercase make/model, strip whitespace, cast numeric fields, drop electric vehicles.',
    icon: <AdjustmentsHorizontalIcon style={{ width: 16, height: 16 }} />,
  },
  {
    id: 'deduplicate',
    label: 'Deduplicate',
    description: 'Remove exact duplicate make/model/engine/fuel rows. Last occurrence wins.',
    icon: <FunnelIcon style={{ width: 16, height: 16 }} />,
  },
  {
    id: 'enrich',
    label: 'Enrich Years',
    description: 'Query fueleconomy.gov → CarAPI → Wikipedia → Wikidata → NHTSA to find production year ranges for each make/model.',
    icon: <ClipboardDocumentListIcon style={{ width: 16, height: 16 }} />,
  },
  {
    id: 'stage',
    label: 'Stage & Review',
    description: 'Enriched rows are written to vehicle_years_staging. Duplicates are detected and conflicts flagged for admin review.',
    icon: <ArchiveBoxIcon style={{ width: 16, height: 16 }} />,
  },
  {
    id: 'commit',
    label: 'Commit to DB',
    description: 'After admin review, approved rows are merged into vehicle_years with a version record created for rollback.',
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
        padding: '0.6rem 1rem', borderBottom: '1px solid var(--adm-sep)',
        background: 'var(--adm-faint-bg)',
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
      background: 'var(--adm-card-bg)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <img src={chlorideExideLogo} alt="Loading" className="loader-battery-svg" style={{ width: 120, height: 'auto' }} />
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
  const [loadingRunP2, setLoadingRunP2]   = useState(false)
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

  // Master record edit/delete
  const [editMasterRow, setEditMasterRow]         = useState<{ id: number; make_n: string; model_n: string; year: number; ah: number|null; technology: string|null; battery_code: string|null } | null>(null)
  const [editMasterPatch, setEditMasterPatch]     = useState<MasterRecordPatch>({})
  const [editMasterScope, setEditMasterScope]     = useState<'single' | 'bucket'>('single')
  const [editMasterSaving, setEditMasterSaving]   = useState(false)
  const [editMasterError, setEditMasterError]     = useState<string | null>(null)

  // Fix-Ah
  const [fixAhLoading, setFixAhLoading]           = useState(false)
  const [fixAhToast, setFixAhToast]               = useState<string | null>(null)

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
      await runWebValidatePipeline([...enabledProviders], 'phase1')
      const s = await getWebValidateStatus()
      setStatus(s)
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoadingRun(false)
    }
  }

  async function handleRunPhase2() {
    setActionError(null)
    setLoadingRunP2(true)
    try {
      await runWebValidatePipeline([...enabledProviders], 'phase2')
      const s = await getWebValidateStatus()
      setStatus(s)
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoadingRunP2(false)
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
          /* ── Idle state: Phase 1 + conditional Phase 2 buttons ── */
          (loadingRun || loadingRunP2) ? (
            <img src={chlorideExideLogo} alt="Starting…" className="loader-battery-svg" style={{ width: 64, height: 'auto' }} />
          ) : (
          <>
            <button
              onClick={handleRun}
              style={{
                display: 'flex', alignItems: 'center', gap: '0.45rem',
                fontSize: '0.82rem', fontWeight: 700,
                padding: '0.65rem 1.35rem', borderRadius: 10, border: 'none',
                cursor: 'pointer', background: R, color: '#fff', transition: 'background 0.15s',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = RD }}
              onMouseLeave={e => { e.currentTarget.style.background = R }}
            >
              <PlayIcon style={{ width: 14, height: 14 }} />
              Run Phase 1
            </button>
            {/* Phase 2 button — shown when Phase 1 has run but Phase 2 hasn't */}
            {(status?.phase1_total ?? 0) > 0 && (status?.processed ?? 0) === 0 && (
              <button
                onClick={handleRunPhase2}
                style={{
                  display: 'flex', alignItems: 'center', gap: '0.45rem',
                  fontSize: '0.82rem', fontWeight: 700,
                  padding: '0.65rem 1.35rem', borderRadius: 10, border: 'none',
                  cursor: 'pointer', background: '#3b82f6', color: '#fff', transition: 'background 0.15s',
                }}
                onMouseEnter={e => { e.currentTarget.style.background = '#2563eb' }}
                onMouseLeave={e => { e.currentTarget.style.background = '#3b82f6' }}
              >
                <PlayIcon style={{ width: 14, height: 14 }} />
                Run Phase 2
              </button>
            )}
          </>
          )
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
            background: 'var(--adm-card-bg)', color: 'var(--adm-text-2)',
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
              <span key={p} style={{ fontSize: '0.7rem', background: 'var(--adm-subtle-bg)', borderRadius: 99, padding: '0.2rem 0.6rem', color: 'var(--adm-text-1)', fontWeight: 600 }}>
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
                  Phase 1 — Web Prefetch
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
                <span key={p} style={{ fontSize: '0.7rem', background: 'var(--adm-subtle-bg)', borderRadius: 99, padding: '0.2rem 0.6rem', color: 'var(--adm-text-1)', fontWeight: 600 }}>
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
        <h3 style={{ margin: '0 0 1rem', fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.8)', display: 'inline-block' }}>
          Battery Coverage
        </h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
          {/* Coverage stat tiles */}
          <div style={{ flex: 1, display: 'flex', flexWrap: 'wrap', gap: '0.55rem', alignItems: 'flex-start' }}>
            {([
              { label: 'Total Combos',        value: totalCount.toLocaleString(),                                  color: '#9ca3af' },
              { label: 'Matched',             value: matchedCount.toLocaleString(),                               color: '#22c55e' },
              { label: 'Unmatched',           value: unmatchedCount.toLocaleString(),                             color: unmatchedCount > 0 ? R : '#22c55e' },
              { label: 'Committed to Master', value: (coverage?.master_count ?? 0).toLocaleString(),              color: '#16a34a' },
              ...((coverage?.staging_count ?? 0) > 0 ? [{ label: 'In Staging', value: (coverage!.staging_count).toLocaleString(), color: '#f59e0b' }] : []),
              { label: 'Buckets Remaining',   value: (coverage?.remaining_buckets ?? 0).toLocaleString(),         color: '#6366f1' },
              { label: 'In Web Cache',        value: (coverage?.web_cache_size ?? 0).toLocaleString(),            color: '#0ea5e9' },
            ] as { label: string; value: string; color: string }[]).map(({ label, value, color }) => (
              <div key={label} style={{
                background: 'var(--adm-subtle-bg)', border: '1px solid var(--adm-card-border)',
                borderRadius: 10, padding: '0.55rem 0.9rem', minWidth: 90, textAlign: 'center',
              }}>
                <div style={{ fontSize: '1.25rem', fontWeight: 800, color, lineHeight: 1 }}>{value}</div>
                <div style={{ fontSize: '0.62rem', color: 'var(--adm-text-2)', marginTop: 4, fontWeight: 500 }}>{label}</div>
              </div>
            ))}
          </div>

          {/* Right: SVG donut chart */}
          {(() => {
            const r = 45, cx = 60, cy = 60
            const circ = 2 * Math.PI * r
            const arc  = (matchedPct / 100) * circ
            return (
              <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.25rem' }}>
                <svg width="110" height="110" viewBox="0 0 120 120">
                  <circle cx={cx} cy={cy} r={r} fill="none" stroke="#e2e4e9" strokeWidth="15" />
                  {matchedPct > 0 && (
                    <circle
                      cx={cx} cy={cy} r={r} fill="none"
                      stroke="#22c55e" strokeWidth="15"
                      strokeDasharray={`${arc} ${circ - arc}`}
                      transform={`rotate(-90 ${cx} ${cy})`}
                      style={{ transition: 'stroke-dasharray 0.6s ease' }}
                    />
                  )}
                  <text x={cx} y={cy - 4} textAnchor="middle" fontSize="17" fontWeight="800" fill="rgba(17,24,39,0.88)">{matchedPct.toFixed(1)}%</text>
                  <text x={cx} y={cy + 12} textAnchor="middle" fontSize="8.5" fill="#6b7280" letterSpacing="0.08em">COVERED</text>
                </svg>
              </div>
            )
          })()}
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
                <span key={label} style={{ fontSize: '0.7rem', fontWeight: 700, background: 'var(--adm-card-bg)', border: '1px solid var(--adm-sep)', borderRadius: 99, padding: '0.2rem 0.6rem', color }}>
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
                style={{ padding: '0.3rem', border: '1px solid var(--adm-sep)', borderRadius: 6, background: 'var(--adm-card-bg)', cursor: stagingPage === 1 ? 'not-allowed' : 'pointer', opacity: stagingPage === 1 ? 0.4 : 1 }}>
                <ChevronLeftIcon style={{ width: 14, height: 14 }} />
              </button>
              <button disabled={stagingPage * 50 >= stagingInfo.total} onClick={() => handleStagingPageChange(stagingPage + 1)}
                style={{ padding: '0.3rem', border: '1px solid var(--adm-sep)', borderRadius: 6, background: 'var(--adm-card-bg)', cursor: stagingPage * 50 >= stagingInfo.total ? 'not-allowed' : 'pointer', opacity: stagingPage * 50 >= stagingInfo.total ? 0.4 : 1 }}>
                <ChevronRightIcon style={{ width: 14, height: 14 }} />
              </button>
            </div>
          )}

          {/* Action buttons */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', marginTop: '1rem', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
            {fixAhToast && (
              <span style={{ fontSize: '0.72rem', color: '#15803d', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 6, padding: '0.3rem 0.6rem' }}>
                {fixAhToast}
              </span>
            )}
            <button
              disabled={fixAhLoading}
              onClick={async () => {
                setFixAhLoading(true); setFixAhToast(null)
                try {
                  const r = await fixStagingAh()
                  setFixAhToast(`Fixed ${r.fixed} · ${r.unchanged} unchanged · ${r.failed} failed`)
                  const s = await getStagingArea(stagingPage, 50, stagingFilter)
                  setStagingInfo(s)
                } catch (e) { alert(e instanceof Error ? e.message : 'Fix Ah failed') }
                finally { setFixAhLoading(false) }
              }}
              style={{
                display: 'flex', alignItems: 'center', gap: '0.4rem',
                fontSize: '0.78rem', fontWeight: 700,
                padding: '0.55rem 1.1rem', borderRadius: 9, cursor: fixAhLoading ? 'not-allowed' : 'pointer',
                border: '1px solid #d97706', background: 'var(--adm-card-bg)', color: '#d97706', opacity: fixAhLoading ? 0.6 : 1,
              }}
            >
              <WrenchScrewdriverIcon style={{ width: 13, height: 13 }} />
              {fixAhLoading ? 'Fixing…' : 'Fix Suspicious Ah'}
            </button>
            <button
              onClick={() => { if (window.confirm('Discard all staged data? This will remove the staged records from the master table and cannot be undone.')) handleDiscard() }}
              disabled={discardLoading}
              style={{
                display: 'flex', alignItems: 'center', gap: '0.4rem',
                fontSize: '0.78rem', fontWeight: 700,
                padding: '0.55rem 1.1rem', borderRadius: 9, cursor: discardLoading ? 'not-allowed' : 'pointer',
                border: `1px solid ${R}`, background: 'var(--adm-card-bg)', color: R, opacity: discardLoading ? 0.6 : 1,
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
          <p style={{ fontSize: '0.68rem', color: '#92400e', margin: '0.5rem 0 0', fontStyle: 'italic' }}>
            Discard removes staged records only — the Phase 1 web search cache is preserved.
          </p>
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
                      <tr style={{ background: 'var(--adm-thead-bg)' }}>
                        {['Version', 'Committed At', 'Committed By', 'Pipeline Run By', 'Committed', 'Removed', 'Conflicts', ''].map(col => (
                          <th key={col} style={{ padding: '0.5rem 0.75rem', textAlign: 'left', fontWeight: 700, color: 'rgba(107,114,128,0.9)', fontSize: '0.65rem', textTransform: 'uppercase', letterSpacing: '0.07em', whiteSpace: 'nowrap' }}>
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {versions.map((v, i) => (
                        <tr key={v.id} style={{ background: i % 2 === 0 ? 'var(--adm-card-bg)' : 'var(--adm-faint-bg)', borderBottom: '1px solid var(--adm-sep)' }}>
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
                      style={{ padding: '0.3rem', border: '1px solid var(--adm-sep)', borderRadius: 6, background: 'var(--adm-card-bg)', cursor: versionsPage === 1 ? 'not-allowed' : 'pointer', opacity: versionsPage === 1 ? 0.4 : 1 }}>
                      <ChevronLeftIcon style={{ width: 14, height: 14 }} />
                    </button>
                    <button disabled={versionsPage * 20 >= versionsTotal} onClick={() => fetchVersions(versionsPage + 1)}
                      style={{ padding: '0.3rem', border: '1px solid var(--adm-sep)', borderRadius: 6, background: 'var(--adm-card-bg)', cursor: versionsPage * 20 >= versionsTotal ? 'not-allowed' : 'pointer', opacity: versionsPage * 20 >= versionsTotal ? 0.4 : 1 }}>
                      <ChevronRightIcon style={{ width: 14, height: 14 }} />
                    </button>
                  </div>
                )}
              </>
            )}

            {/* Inline changelog drawer */}
            {openChangelog && (
              <div style={{ marginTop: '1rem', background: 'var(--adm-faint-bg)', border: '1px solid var(--adm-sep)', borderRadius: 10, padding: '1rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                  <span style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--adm-text-1)' }}>
                    Changelog for Version #{openChangelog.version.version_number}
                  </span>
                  <button onClick={() => setOpenChangelog(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--adm-text-2)' }}>
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
                      <tr style={{ background: 'var(--adm-thead-bg)' }}>
                        {['Make', 'Model', 'Year', 'Ah', 'Technology', 'Source', ''].map(col => (
                          <th key={col} style={{ padding: '0.5rem 0.75rem', textAlign: 'left', fontWeight: 700, color: 'rgba(107,114,128,0.9)', fontSize: '0.65rem', textTransform: 'uppercase', letterSpacing: '0.07em', whiteSpace: 'nowrap' }}>
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(matchedData?.items.length ?? 0) === 0 ? (
                        <tr><td colSpan={7} style={{ padding: '1rem', textAlign: 'center', color: '#9ca3af' }}>No results</td></tr>
                      ) : matchedData!.items.map((v, i) => (
                        <tr key={i} style={{ background: i % 2 === 0 ? '#fff' : '#f9fafb', borderBottom: '1px solid #e2e4e9' }}>
                          <td style={{ padding: '0.5rem 0.75rem', fontWeight: 600 }}>{v.make_n}</td>
                          <td style={{ padding: '0.5rem 0.75rem' }}>{v.model_n}</td>
                          <td style={{ padding: '0.5rem 0.75rem' }}>{v.year}</td>
                          <td style={{ padding: '0.5rem 0.75rem', color: '#22c55e', fontWeight: 600 }}>{v.ah != null ? `${v.ah} Ah` : '—'}</td>
                          <td style={{ padding: '0.5rem 0.75rem', color: '#6b7280' }}>{v.technology ?? '—'}</td>
                          <td style={{ padding: '0.5rem 0.75rem', color: '#6b7280' }}>{v.source ? (PROVIDER_LABELS[v.source] ?? v.source) : '—'}</td>
                          <td style={{ padding: '0.35rem 0.5rem', whiteSpace: 'nowrap' }}>
                            <button
                              title="Edit"
                              onClick={() => { setEditMasterRow({ id: v.id, make_n: v.make_n, model_n: v.model_n, year: v.year, ah: v.ah, technology: v.technology, battery_code: v.battery_code }); setEditMasterPatch({}); setEditMasterScope('single'); setEditMasterError(null) }}
                              style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6b7280', padding: '0.2rem', borderRadius: 4 }}
                            ><PencilIcon style={{ width: 13, height: 13 }} /></button>
                            <button
                              title="Delete"
                              onClick={async () => {
                                if (!window.confirm(`Delete ${v.make_n} ${v.model_n} ${v.year}? This creates a version record.`)) return
                                try {
                                  await deleteMasterRecord(v.id)
                                  const md = await getWebValidateMatched(matchedPage, 50, matchedSearch)
                                  setMatchedData(md)
                                  const cov = await getWebValidateCoverage()
                                  setCoverage(cov)
                                } catch (e) { alert(e instanceof Error ? e.message : 'Delete failed') }
                              }}
                              style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#ef4444', padding: '0.2rem', borderRadius: 4 }}
                            ><TrashIcon style={{ width: 13, height: 13 }} /></button>
                          </td>
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
                    style={{ padding: '0.3rem', border: '1px solid var(--adm-sep)', borderRadius: 6, background: 'var(--adm-card-bg)', cursor: matchedPage === 1 ? 'not-allowed' : 'pointer', opacity: matchedPage === 1 ? 0.4 : 1 }}
                  >
                    <ChevronLeftIcon style={{ width: 14, height: 14 }} />
                  </button>
                  <button
                    disabled={matchedPage * 50 >= matchedData.total}
                    onClick={() => setMatchedPage(p => p + 1)}
                    style={{ padding: '0.3rem', border: '1px solid var(--adm-sep)', borderRadius: 6, background: 'var(--adm-card-bg)', cursor: matchedPage * 50 >= matchedData.total ? 'not-allowed' : 'pointer', opacity: matchedPage * 50 >= matchedData.total ? 0.4 : 1 }}
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
                    <tr style={{ background: 'var(--adm-thead-bg)' }}>
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
                    style={{ padding: '0.3rem', border: '1px solid var(--adm-sep)', borderRadius: 6, background: 'var(--adm-card-bg)', cursor: coveragePage === 1 ? 'not-allowed' : 'pointer', opacity: coveragePage === 1 ? 0.4 : 1 }}
                  >
                    <ChevronLeftIcon style={{ width: 14, height: 14 }} />
                  </button>
                  <button
                    disabled={coveragePage === totalPages}
                    onClick={() => setCoveragePage(p => p + 1)}
                    style={{ padding: '0.3rem', border: '1px solid var(--adm-sep)', borderRadius: 6, background: 'var(--adm-card-bg)', cursor: coveragePage === totalPages ? 'not-allowed' : 'pointer', opacity: coveragePage === totalPages ? 0.4 : 1 }}
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
                style={{ padding: '0.4rem 0.9rem', borderRadius: 6, border: '1px solid var(--adm-input-border)', background: 'var(--adm-input-bg)', color: 'var(--adm-text-1)', cursor: 'pointer', fontSize: '0.8rem' }}
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

      {/* ── Edit Master Record Modal ── */}
      {editMasterRow && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '1rem' }}>
          <div style={{ ...CARD, padding: '1.5rem', maxWidth: 380, width: '100%' }}>
            <h2 style={{ margin: '0 0 0.1rem', fontSize: '0.95rem', fontWeight: 700, color: '#111827' }}>Edit Master Record</h2>
            <p style={{ margin: '0 0 1rem', fontSize: '0.72rem', color: '#6b7280' }}>
              {editMasterRow.make_n} {editMasterRow.model_n} {editMasterRow.year}
            </p>

            <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 600, color: '#374151', marginBottom: '0.25rem' }}>Scope</label>
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem' }}>
              {(['single', 'bucket'] as const).map(s => (
                <button key={s} onClick={() => setEditMasterScope(s)}
                  style={{ flex: 1, padding: '0.35rem', borderRadius: 6, border: `1px solid ${editMasterScope === s ? R : '#d1d5db'}`, background: editMasterScope === s ? '#fff5f5' : 'transparent', color: editMasterScope === s ? R : '#374151', fontSize: '0.75rem', cursor: 'pointer', fontWeight: editMasterScope === s ? 600 : 400 }}>
                  {s === 'single' ? 'Single row' : `5-yr bucket (${Math.floor(editMasterRow.year/5)*5}–${Math.floor(editMasterRow.year/5)*5+4})`}
                </button>
              ))}
            </div>

            <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 600, color: '#374151', marginBottom: '0.25rem' }}>Battery Code</label>
            <input type="text"
              defaultValue={editMasterRow.battery_code ?? ''}
              onChange={e => setEditMasterPatch(p => ({ ...p, battery_code: e.target.value || null }))}
              placeholder="e.g. NS60"
              style={{ width: '100%', boxSizing: 'border-box', border: '1px solid #d1d5db', borderRadius: 6, padding: '0.4rem 0.6rem', fontSize: '0.82rem', marginBottom: '0.75rem' }} />

            <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 600, color: '#374151', marginBottom: '0.25rem' }}>Ah (20–250)</label>
            <input type="number"
              defaultValue={editMasterRow.ah ?? ''}
              onChange={e => setEditMasterPatch(p => ({ ...p, ah: e.target.value ? Number(e.target.value) : null }))}
              min={20} max={250} step={1}
              style={{ width: '100%', boxSizing: 'border-box', border: '1px solid #d1d5db', borderRadius: 6, padding: '0.4rem 0.6rem', fontSize: '0.82rem', marginBottom: '0.75rem' }} />

            <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 600, color: '#374151', marginBottom: '0.25rem' }}>Technology</label>
            <select
              defaultValue={editMasterRow.technology ?? ''}
              onChange={e => setEditMasterPatch(p => ({ ...p, technology: e.target.value || null }))}
              style={{ width: '100%', border: '1px solid #d1d5db', borderRadius: 6, padding: '0.4rem 0.6rem', fontSize: '0.82rem', marginBottom: '1rem' }}>
              <option value="">— none —</option>
              {['MF', 'AGM', 'EFB', 'GEL', 'WET'].map(t => <option key={t} value={t}>{t}</option>)}
            </select>

            {editMasterError && (
              <p style={{ margin: '0 0 0.75rem', fontSize: '0.72rem', color: '#dc2626', background: '#fee2e2', borderRadius: 6, padding: '0.4rem 0.6rem' }}>{editMasterError}</p>
            )}

            <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
              <button onClick={() => setEditMasterRow(null)} disabled={editMasterSaving}
                style={{ padding: '0.4rem 0.9rem', borderRadius: 6, border: '1px solid var(--adm-input-border)', background: 'var(--adm-input-bg)', color: 'var(--adm-text-1)', cursor: 'pointer', fontSize: '0.8rem' }}>
                Cancel
              </button>
              <button
                disabled={editMasterSaving}
                onClick={async () => {
                  setEditMasterSaving(true); setEditMasterError(null)
                  try {
                    await patchMasterRecord(editMasterRow!.id, { ...editMasterPatch, scope: editMasterScope })
                    setEditMasterRow(null)
                    const md = await getWebValidateMatched(matchedPage, 50, matchedSearch)
                    setMatchedData(md)
                  } catch (e) { setEditMasterError(e instanceof Error ? e.message : 'Save failed') }
                  finally { setEditMasterSaving(false) }
                }}
                style={{ padding: '0.4rem 0.9rem', borderRadius: 6, border: 'none', background: '#3b82f6', color: '#fff', cursor: editMasterSaving ? 'not-allowed' : 'pointer', fontSize: '0.8rem', fontWeight: 600, opacity: editMasterSaving ? 0.7 : 1 }}>
                {editMasterSaving ? 'Saving…' : 'Save'}
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
                    style={{ padding: '0.6rem 1.1rem', borderRadius: 9, border: '1px solid var(--adm-sep)', background: 'var(--adm-card-bg)', color: 'var(--adm-text-1)', fontWeight: 600, fontSize: '0.8rem', cursor: 'pointer' }}>
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
                style={{ padding: '0.6rem 1.1rem', borderRadius: 9, border: '1px solid var(--adm-sep)', background: 'var(--adm-card-bg)', color: 'var(--adm-text-1)', fontWeight: 600, fontSize: '0.8rem', cursor: 'pointer' }}
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

// ── CrspTab ───────────────────────────────────────────────────────────────────
const SOURCE_LABELS: Record<string, string> = {
  fueleconomy: 'fueleconomy.gov',
  carapi:      'CarAPI',
  wikipedia:   'Wikipedia',
  wikidata:    'Wikidata',
  nhtsa:       'NHTSA VPIC',
  not_found:   'Not Found',
}

function CacheStatusBadge({ onRefresh }: { onRefresh: () => void }) {
  const [cache, setCache] = useState<CrspCacheStatus | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  useEffect(() => {
    getCrspCacheStatus().then(setCache).catch(() => null)
  }, [])

  async function handleRefresh() {
    setRefreshing(true)
    setMsg(null)
    try {
      await refreshCrspCache()
      setMsg('Cache cleared — next run will re-download all datasets')
      const fresh = await getCrspCacheStatus()
      setCache(fresh)
      onRefresh()
    } catch {
      setMsg('Failed to clear cache')
    } finally {
      setRefreshing(false)
    }
  }

  if (!cache) return null

  const fe   = cache.fueleconomy_csv
  const yc   = cache.year_cache
  const overdue = fe.overdue || yc.overdue
  const stale   = fe.stale   || yc.stale

  const chipColor = overdue ? R : stale ? '#b45309' : '#15803d'
  const chipBg    = overdue ? '#fff5f5' : stale ? '#fffbeb' : '#f0fdf4'
  const chipBorder= overdue ? '#fca5a5' : stale ? '#fde68a' : '#bbf7d0'

  const oldestAge = Math.max(fe.age_days ?? 0, yc.age_days ?? 0)
  const label = fe.downloaded_at
    ? (overdue ? 'Dataset overdue — refresh required' : stale ? 'Dataset aging — refresh recommended' : `Dataset: ${oldestAge} days old`)
    : 'Dataset: not yet downloaded'

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: '0.4rem',
        padding: '0.3rem 0.75rem', borderRadius: 99,
        background: chipBg, border: `1px solid ${chipBorder}`,
        fontSize: '0.72rem', fontWeight: 700, color: chipColor,
      }}>
        <ClockIcon style={{ width: 12, height: 12, flexShrink: 0 }} />
        {label}
      </div>
      <button
        onClick={handleRefresh}
        disabled={refreshing}
        title="Force re-download on next pipeline run"
        style={{
          display: 'flex', alignItems: 'center', gap: '0.35rem',
          padding: '0.3rem 0.7rem', borderRadius: 99, border: '1px solid #e2e4e9',
          background: 'var(--adm-card-bg)', fontSize: '0.7rem', fontWeight: 600,
          cursor: refreshing ? 'not-allowed' : 'pointer', color: 'var(--adm-text-2)',
        }}
      >
        <ArrowPathIcon style={{ width: 12, height: 12 }} />
        {refreshing ? 'Clearing…' : 'Refresh Cache'}
      </button>
      {msg && <span style={{ fontSize: '0.7rem', color: overdue ? R : '#15803d' }}>{msg}</span>}
    </div>
  )
}

function CrspStatsPanel() {
  const [stats, setStats] = useState<CrspStats | null>(null)

  useEffect(() => {
    getCrspStats().then(setStats).catch(() => null)
  }, [])

  if (!stats) return null

  return (
    <div style={{ ...CARD, padding: '1.1rem 1.25rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
        <ServerStackIcon style={{ width: 14, height: 14, color: '#6b7280' }} />
        <span style={{ fontSize: '0.7rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', color: '#9ca3af' }}>
          Vehicle Years Database
        </span>
        {stats.staging_pending > 0 && (
          <span style={{ fontSize: '0.65rem', fontWeight: 700, color: '#b45309', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 99, padding: '0.1rem 0.5rem' }}>
            {stats.staging_pending} rows pending review
          </span>
        )}
      </div>
      <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
        <SummaryBadge label="Total Rows"   value={stats.total_rows.toLocaleString()} />
        <SummaryBadge label="Makes"        value={stats.total_makes.toLocaleString()} />
        <SummaryBadge label="Combinations" value={stats.total_combinations.toLocaleString()} color="#3b82f6" />
      </div>
      {stats.by_make.length > 0 && (
        <div style={{ maxHeight: 220, overflowY: 'auto', borderTop: '1px solid var(--adm-sep)', paddingTop: '0.5rem' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.72rem' }}>
            <thead>
              <tr>
                {['Make', 'Models', 'Years'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '0.25rem 0.5rem', color: '#9ca3af', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: '0.6rem' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {stats.by_make.map(r => (
                <tr key={r.make} style={{ borderTop: '1px solid var(--adm-sep)' }}>
                  <td style={{ padding: '0.3rem 0.5rem', fontWeight: 700 }}>{r.make}</td>
                  <td style={{ padding: '0.3rem 0.5rem', color: '#374151' }}>{r.model_count}</td>
                  <td style={{ padding: '0.3rem 0.5rem', color: '#6b7280' }}>
                    {r.year_min && r.year_max ? `${r.year_min}–${r.year_max}` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function CrspStagingPanel({
  onCommit,
  onDiscard,
}: {
  onCommit: (result: CrspCommitResult) => void
  onDiscard: () => void
}) {
  const [data, setData]               = useState<CrspStagingResponse | null>(null)
  const [filter, setFilter]           = useState<'all' | 'conflicts' | 'new'>('all')
  const [page, setPage]               = useState(1)
  const [loading, setLoading]         = useState(false)
  const [editingId, setEditingId]     = useState<number | null>(null)
  const [editEc, setEditEc]           = useState('')
  const [editFuel, setEditFuel]       = useState('')
  const [editSaving, setEditSaving]   = useState(false)
  const [commitLoading, setCommitLoading] = useState(false)
  const [discardLoading, setDiscardLoading] = useState(false)
  const [resolutions, setResolutions] = useState<Record<string, 'staged' | 'current'>>({})
  const [toast, setToast]             = useState<string | null>(null)

  const PAGE_SIZE = 50

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const d = await getCrspStaging(filter, page, PAGE_SIZE)
      setData(d)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [filter, page])

  useEffect(() => { load() }, [load])

  async function saveEdit(rowId: number) {
    setEditSaving(true)
    try {
      await patchCrspStagingRow(rowId, {
        engine_capacity: editEc !== '' ? parseInt(editEc) : null,
        fuel: editFuel || null,
      })
      setEditingId(null)
      load()
    } catch { /* ignore */ }
    finally { setEditSaving(false) }
  }

  async function handlePreCommit() {
    const r = await crspPreCommit()
    setToast(`Re-scanned ${r.rows_rescanned} rows — ${r.total_conflicts} conflicts`)
    load()
  }

  async function handleCommit() {
    setCommitLoading(true)
    try {
      const cr: CrspConflictResolution[] = Object.entries(resolutions).map(([key, resolution]) => {
        const [make, model, year] = key.split('|')
        return { make, model, year: parseInt(year), resolution }
      })
      const result = await commitCrspStaging(cr)
      onCommit(result)
    } catch { /* ignore */ }
    finally { setCommitLoading(false) }
  }

  async function handleDiscard() {
    setDiscardLoading(true)
    try {
      await discardCrspStaging()
      onDiscard()
    } catch { /* ignore */ }
    finally { setDiscardLoading(false) }
  }

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 1
  const conflictCount = data?.rows.filter(r => r.conflict).length ?? 0

  return (
    <div style={{ ...CARD, padding: '1.1rem 1.25rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem', flexWrap: 'wrap', gap: '0.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <ArchiveBoxIcon style={{ width: 14, height: 14, color: '#6b7280' }} />
          <span style={{ fontSize: '0.8rem', fontWeight: 700 }}>
            Stage & Review{data ? ` — ${data.total.toLocaleString()} rows staged` : ''}
          </span>
          {conflictCount > 0 && (
            <span style={{ fontSize: '0.65rem', fontWeight: 700, color: '#b45309', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 99, padding: '0.1rem 0.5rem' }}>
              {conflictCount} conflicts
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          {(['all', 'conflicts', 'new'] as const).map(f => (
            <button
              key={f}
              onClick={() => { setFilter(f); setPage(1) }}
              style={{
                fontSize: '0.7rem', fontWeight: 600, padding: '0.25rem 0.65rem', borderRadius: 99,
                border: '1px solid', cursor: 'pointer',
                borderColor: filter === f ? R : '#e2e4e9',
                background: filter === f ? '#fff5f5' : 'var(--adm-card-bg)',
                color: filter === f ? R : 'var(--adm-text-2)',
              }}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {toast && (
        <div style={{ fontSize: '0.72rem', color: '#15803d', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8, padding: '0.4rem 0.75rem', marginBottom: '0.5rem' }}>
          {toast}
        </div>
      )}

      <div style={{ overflowX: 'auto', marginBottom: '0.75rem' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.72rem' }}>
          <thead>
            <tr>
              {['Make', 'Model', 'Year', 'Engine CC', 'Fuel', 'Source', 'Status', ''].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '0.3rem 0.5rem', color: '#9ca3af', fontWeight: 700, fontSize: '0.6rem', textTransform: 'uppercase', letterSpacing: '0.08em', whiteSpace: 'nowrap' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading
              ? <tr><td colSpan={8} style={{ padding: '1rem', color: '#9ca3af', textAlign: 'center' }}>Loading…</td></tr>
              : !data?.rows.length
              ? <tr><td colSpan={8} style={{ padding: '1rem', color: '#9ca3af', textAlign: 'center', fontStyle: 'italic' }}>No rows</td></tr>
              : data.rows.map(row => {
                  const rowBg = row.conflict ? '#fffbeb' : !row.is_valid ? '#fff5f5' : 'transparent'
                  const resKey = `${row.make}|${row.model}|${row.year}`
                  return (
                    <tr key={row.id} style={{ borderTop: '1px solid var(--adm-sep)', background: rowBg }}>
                      <td style={{ padding: '0.3rem 0.5rem', fontWeight: 700 }}>{row.make}</td>
                      <td style={{ padding: '0.3rem 0.5rem' }}>{row.model}</td>
                      <td style={{ padding: '0.3rem 0.5rem' }}>{row.year}</td>
                      <td style={{ padding: '0.3rem 0.5rem' }}>
                        {editingId === row.id
                          ? <input value={editEc} onChange={e => setEditEc(e.target.value)} style={{ width: 60, fontSize: '0.72rem', padding: '0.15rem 0.35rem', border: '1px solid #d1d5db', borderRadius: 5 }} />
                          : row.engine_capacity ?? <span style={{ color: '#9ca3af' }}>—</span>}
                      </td>
                      <td style={{ padding: '0.3rem 0.5rem' }}>
                        {editingId === row.id
                          ? <input value={editFuel} onChange={e => setEditFuel(e.target.value)} style={{ width: 70, fontSize: '0.72rem', padding: '0.15rem 0.35rem', border: '1px solid #d1d5db', borderRadius: 5 }} />
                          : row.fuel ?? <span style={{ color: '#9ca3af' }}>—</span>}
                      </td>
                      <td style={{ padding: '0.3rem 0.5rem', color: '#6b7280' }}>{row.source ? (SOURCE_LABELS[row.source] ?? row.source) : '—'}</td>
                      <td style={{ padding: '0.3rem 0.5rem' }}>
                        {row.conflict
                          ? <span style={{ color: '#b45309', fontWeight: 700, fontSize: '0.65rem' }}>⚠ Conflict</span>
                          : !row.is_valid
                          ? <span style={{ color: R, fontSize: '0.65rem' }}>{row.invalid_reason ?? 'Invalid'}</span>
                          : <span style={{ color: '#15803d', fontSize: '0.65rem' }}>✓ New</span>}
                      </td>
                      <td style={{ padding: '0.3rem 0.5rem', whiteSpace: 'nowrap' }}>
                        {row.conflict && (
                          <select
                            value={resolutions[resKey] ?? 'staged'}
                            onChange={e => setResolutions(prev => ({ ...prev, [resKey]: e.target.value as 'staged' | 'current' }))}
                            style={{ fontSize: '0.65rem', padding: '0.15rem 0.3rem', border: '1px solid #e2e4e9', borderRadius: 5, marginRight: 4 }}
                          >
                            <option value="staged">Use new</option>
                            <option value="current">Keep existing</option>
                          </select>
                        )}
                        {editingId === row.id ? (
                          <>
                            <button onClick={() => saveEdit(row.id)} disabled={editSaving} style={{ fontSize: '0.65rem', padding: '0.15rem 0.4rem', borderRadius: 5, border: 'none', background: '#22c55e', color: '#fff', cursor: 'pointer', marginRight: 3 }}>
                              {editSaving ? '…' : 'Save'}
                            </button>
                            <button onClick={() => setEditingId(null)} style={{ fontSize: '0.65rem', padding: '0.15rem 0.4rem', borderRadius: 5, border: '1px solid #e2e4e9', background: 'var(--adm-card-bg)', cursor: 'pointer' }}>
                              Cancel
                            </button>
                          </>
                        ) : (
                          <button
                            onClick={() => { setEditingId(row.id); setEditEc(row.engine_capacity?.toString() ?? ''); setEditFuel(row.fuel ?? '') }}
                            style={{ fontSize: '0.65rem', padding: '0.15rem 0.4rem', borderRadius: 5, border: '1px solid #e2e4e9', background: 'var(--adm-card-bg)', cursor: 'pointer' }}
                          >
                            Edit
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })
            }
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', justifyContent: 'center', marginBottom: '0.75rem' }}>
          <button disabled={page === 1} onClick={() => setPage(p => p - 1)} style={{ padding: '0.2rem 0.5rem', border: '1px solid #e2e4e9', borderRadius: 6, cursor: page === 1 ? 'not-allowed' : 'pointer', background: 'var(--adm-card-bg)' }}>
            <ChevronLeftIcon style={{ width: 12, height: 12 }} />
          </button>
          <span style={{ fontSize: '0.7rem', color: '#6b7280' }}>Page {page} / {totalPages}</span>
          <button disabled={page === totalPages} onClick={() => setPage(p => p + 1)} style={{ padding: '0.2rem 0.5rem', border: '1px solid #e2e4e9', borderRadius: 6, cursor: page === totalPages ? 'not-allowed' : 'pointer', background: 'var(--adm-card-bg)' }}>
            <ChevronRightIcon style={{ width: 12, height: 12 }} />
          </button>
        </div>
      )}

      {/* Action row */}
      <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', borderTop: '1px solid var(--adm-sep)', paddingTop: '0.75rem' }}>
        <button onClick={handlePreCommit} style={{ fontSize: '0.75rem', fontWeight: 600, padding: '0.45rem 0.9rem', borderRadius: 8, border: '1px solid #e2e4e9', background: 'var(--adm-card-bg)', cursor: 'pointer', color: 'var(--adm-text-1)' }}>
          Re-check Conflicts
        </button>
        <button onClick={handleDiscard} disabled={discardLoading} style={{ fontSize: '0.75rem', fontWeight: 600, padding: '0.45rem 0.9rem', borderRadius: 8, border: `1px solid ${R}`, background: 'var(--adm-card-bg)', cursor: 'pointer', color: R }}>
          {discardLoading ? 'Discarding…' : 'Discard All'}
        </button>
        <button onClick={handleCommit} disabled={commitLoading} style={{ fontSize: '0.75rem', fontWeight: 700, padding: '0.45rem 0.9rem', borderRadius: 8, border: 'none', background: R, cursor: 'pointer', color: '#fff' }}>
          {commitLoading ? 'Committing…' : 'Commit to vehicle_years'}
        </button>
      </div>
    </div>
  )
}

function CrspVersionHistoryPanel() {
  const [open, setOpen]                 = useState(false)
  const [data, setData]                 = useState<CrspVersionsResponse | null>(null)
  const [page, setPage]                 = useState(1)
  const [loading, setLoading]           = useState(false)
  const [openChangelog, setOpenChangelog] = useState<CrspChangelogResponse | null>(null)
  const [changelogLoading, setChangelogLoading] = useState(false)
  const [revertingId, setRevertingId]   = useState<string | null>(null)

  async function loadVersions(p = 1) {
    setLoading(true)
    try {
      const d = await getCrspVersions(p)
      setData(d)
      setPage(p)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  useEffect(() => { if (open) loadVersions(1) }, [open])

  async function loadChangelog(versionId: string) {
    setChangelogLoading(true)
    try {
      const cl = await getCrspVersionChangelog(versionId)
      setOpenChangelog(cl)
    } catch { /* ignore */ }
    finally { setChangelogLoading(false) }
  }

  async function handleRevert(versionId: string) {
    if (!confirm('Revert vehicle_years to the state before this version? This creates a new version record.')) return
    setRevertingId(versionId)
    try {
      await revertCrspVersion(versionId)
      loadVersions(1)
    } catch { /* ignore */ }
    finally { setRevertingId(null) }
  }

  return (
    <div style={{ ...CARD, overflow: 'hidden' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', padding: '0.85rem 1.25rem', background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <ClockIcon style={{ width: 14, height: 14, color: '#6b7280' }} />
          <span style={{ fontSize: '0.8rem', fontWeight: 700 }}>Version History</span>
        </div>
        <ChevronRightIcon style={{ width: 14, height: 14, color: '#9ca3af', transform: open ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }} />
      </button>

      {open && (
        <div style={{ borderTop: '1px solid var(--adm-sep)', padding: '0.75rem 1.25rem' }}>
          {loading
            ? <div style={{ color: '#9ca3af', fontSize: '0.75rem', padding: '0.5rem 0' }}>Loading versions…</div>
            : !data?.versions.length
            ? <div style={{ color: '#9ca3af', fontSize: '0.75rem', fontStyle: 'italic' }}>No versions yet</div>
            : (
              <div>
                {data.versions.map(v => (
                  <div key={v.id} style={{ borderBottom: '1px solid var(--adm-sep)', paddingBottom: '0.75rem', marginBottom: '0.75rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.4rem' }}>
                      <div>
                        <span style={{ fontSize: '0.82rem', fontWeight: 800 }}>v{v.version_number}</span>
                        <span style={{ fontSize: '0.7rem', color: '#6b7280', marginLeft: 8 }}>
                          {v.committed_at ? new Date(v.committed_at).toLocaleString() : '—'}
                        </span>
                        {v.notes && <span style={{ fontSize: '0.65rem', color: '#9ca3af', marginLeft: 8, fontStyle: 'italic' }}>{v.notes}</span>}
                      </div>
                      <div style={{ display: 'flex', gap: '0.4rem' }}>
                        <button onClick={() => openChangelog?.version_id === v.id ? setOpenChangelog(null) : loadChangelog(v.id)} style={{ fontSize: '0.65rem', padding: '0.15rem 0.45rem', borderRadius: 6, border: '1px solid #e2e4e9', background: 'var(--adm-card-bg)', cursor: 'pointer' }}>
                          {changelogLoading ? '…' : openChangelog?.version_id === v.id ? 'Hide' : 'Changelog'}
                        </button>
                        <button onClick={() => handleRevert(v.id)} disabled={revertingId === v.id} style={{ fontSize: '0.65rem', padding: '0.15rem 0.45rem', borderRadius: 6, border: `1px solid ${R}`, background: 'var(--adm-card-bg)', color: R, cursor: 'pointer' }}>
                          {revertingId === v.id ? 'Reverting…' : 'Revert'}
                        </button>
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.4rem' }}>
                      {[['Added', v.committed_count, '#15803d'], ['Updated', v.updated_count, '#1d4ed8'], ['Conflicts', v.conflict_count, '#b45309']].map(([label, val, color]) => (
                        <span key={label as string} style={{ fontSize: '0.65rem', color: color as string, fontWeight: 700 }}>
                          {val} {label}
                        </span>
                      ))}
                      {v.committed_by && <span style={{ fontSize: '0.65rem', color: '#9ca3af' }}>by {v.committed_by}</span>}
                    </div>

                    {/* Inline changelog */}
                    {openChangelog?.version_id === v.id && (
                      <div style={{ marginTop: '0.6rem', maxHeight: 200, overflowY: 'auto', background: '#f9fafb', borderRadius: 8, padding: '0.5rem 0' }}>
                        {openChangelog.entries.map(e => (
                          <div key={e.id} style={{ display: 'flex', gap: '0.5rem', alignItems: 'baseline', padding: '0.2rem 0.75rem', fontSize: '0.68rem' }}>
                            <span style={{ minWidth: 52, fontWeight: 700, color: e.change_type === 'added' ? '#15803d' : e.change_type === 'removed' ? R : '#1d4ed8' }}>
                              {e.change_type}
                            </span>
                            <span>{e.make} {e.model} {e.year}</span>
                            {e.old_values && e.new_values && (
                              <span style={{ color: '#9ca3af' }}>
                                {JSON.stringify(e.old_values)} → {JSON.stringify(e.new_values)}
                              </span>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}

                {/* Version pagination */}
                {data.total > 20 && (
                  <div style={{ display: 'flex', gap: '0.4rem', justifyContent: 'center', marginTop: '0.25rem' }}>
                    <button disabled={page === 1} onClick={() => loadVersions(page - 1)} style={{ padding: '0.2rem 0.5rem', border: '1px solid #e2e4e9', borderRadius: 6, cursor: page === 1 ? 'not-allowed' : 'pointer', background: 'var(--adm-card-bg)' }}>
                      <ChevronLeftIcon style={{ width: 12, height: 12 }} />
                    </button>
                    <span style={{ fontSize: '0.7rem', color: '#6b7280', alignSelf: 'center' }}>p{page}</span>
                    <button disabled={page * 20 >= data.total} onClick={() => loadVersions(page + 1)} style={{ padding: '0.2rem 0.5rem', border: '1px solid #e2e4e9', borderRadius: 6, cursor: page * 20 >= data.total ? 'not-allowed' : 'pointer', background: 'var(--adm-card-bg)' }}>
                      <ChevronRightIcon style={{ width: 12, height: 12 }} />
                    </button>
                  </div>
                )}
              </div>
            )
          }
        </div>
      )}
    </div>
  )
}

function CrspTab() {
  const [status, setStatus]           = useState<CrspStatus | null>(null)
  const [loading, setLoading]         = useState(true)
  const [actionError, setActionError] = useState<string | null>(null)
  const [runLoading, setRunLoading]   = useState(false)
  const [action, setAction]           = useState<'pause' | 'resume' | 'cancel' | null>(null)
  const [commitResult, setCommitResult] = useState<CrspCommitResult | null>(null)
  const [showStaging, setShowStaging] = useState(false)
  const [stagingKey, setStagingKey]   = useState(0)
  const [cacheRefreshKey, setCacheRefreshKey] = useState(0)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // CRSP upload (Stage 1)
  const [crspFile, setCrspFile]                   = useState<File | null>(null)
  const [crspUploadLoading, setCrspUploadLoading] = useState(false)
  const [crspUploadedPath, setCrspUploadedPath]   = useState<string | null>(null)
  const [crspUploadError, setCrspUploadError]     = useState<string | null>(null)

  const stagingAvailable = status?.status === 'done' || status?.status === 'cancelled'

  function startPolling() {
    if (pollingRef.current) return
    pollingRef.current = setInterval(async () => {
      const s = await getCrspStatus().catch(() => null)
      if (!s) return
      setStatus(s)
      if (s.status !== 'running' && s.status !== 'paused') {
        clearInterval(pollingRef.current!)
        pollingRef.current = null
        if (s.status === 'done' || s.status === 'cancelled') setShowStaging(true)
      }
    }, 1000)
  }

  useEffect(() => {
    getCrspStatus()
      .then(s => { setStatus(s); if (s.status === 'running' || s.status === 'paused') startPolling() })
      .catch(() => null)
      .finally(() => setLoading(false))
    return () => { if (pollingRef.current) clearInterval(pollingRef.current) }
  }, [])

  async function handleRun() {
    setRunLoading(true)
    setActionError(null)
    setCommitResult(null)
    setShowStaging(false)
    try {
      await runCrspPipeline(crspUploadedPath ?? 'battery_lookup_dataset.csv')
      const s = await getCrspStatus()
      setStatus(s)
      startPolling()
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : 'Failed to start pipeline')
    } finally {
      setRunLoading(false)
    }
  }

  async function handleAction(act: 'pause' | 'resume' | 'cancel') {
    setAction(act)
    try {
      if (act === 'pause')  await pauseCrsp()
      if (act === 'resume') await resumeCrsp()
      if (act === 'cancel') {
        await cancelCrsp()
        setShowStaging(true)
        if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null }
      }
      const s = await getCrspStatus()
      setStatus(s)
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : 'Action failed')
    } finally {
      setAction(null)
    }
  }

  if (loading) return <div style={{ padding: '2rem', color: '#9ca3af', textAlign: 'center' }}>Loading…</div>

  const isActive  = status?.status === 'running' || status?.status === 'paused'
  const isDone    = status?.status === 'done'
  const isError   = status?.status === 'error'
  const isIdle    = !status || status.status === 'idle'
  const pct       = status?.total_models ? Math.round((status.processed_models / status.total_models) * 100) : 0

  // Determine stage status for the stage cards
  function getStageStatus(stageId: string): StageStatus {
    if (isIdle) return 'idle'
    if (isError && stageId === 'enrich') return 'error'
    const stageOrder = ['parse', 'validate', 'normalize', 'deduplicate', 'enrich', 'stage', 'commit']
    const currentStageId = status?.status === 'running' || status?.status === 'paused' ? 'enrich' : isDone ? 'commit' : 'idle'
    const currentIdx = stageOrder.indexOf(currentStageId)
    const thisIdx    = stageOrder.indexOf(stageId)
    if (commitResult && stageId === 'commit') return 'done'
    if (showStaging && stageId === 'stage') return 'done'
    if (thisIdx < currentIdx) return 'done'
    if (thisIdx === currentIdx) return status?.status === 'running' ? 'running' : status?.status === 'paused' ? 'running' : 'done'
    return 'idle'
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

      {/* Cache status + info row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', flex: 1, background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 10, padding: '0.65rem 1rem' }}>
          <InformationCircleIcon style={{ width: 15, height: 15, color: '#3b82f6', flexShrink: 0, marginTop: 1 }} />
          <p style={{ margin: 0, fontSize: '0.72rem', color: '#1d4ed8', lineHeight: 1.6 }}>
            Stage 1 (dataprep.py) cleans the CRSP Excel into <code>battery_lookup_dataset.csv</code> first. Stage 2 queries 5 external sources for production years and writes to staging for review before committing to <code>vehicle_years</code>.
          </p>
        </div>
      </div>

      <CacheStatusBadge key={cacheRefreshKey} onRefresh={() => setCacheRefreshKey(k => k + 1)} />

      {/* CRSP Excel upload */}
      <div style={{ ...CARD, padding: '1rem 1.25rem' }}>
        <p style={{ margin: '0 0 0.5rem', fontSize: '0.72rem', fontWeight: 700, color: 'var(--adm-text-1)' }}>
          Upload CRSP Excel (Stage 1)
        </p>
        <p style={{ margin: '0 0 0.75rem', fontSize: '0.7rem', color: '#6b7280', lineHeight: 1.5 }}>
          Upload a raw CRSP <code>.xlsx</code> file to process it through Stage 1 (dataprep). The cleaned CSV will be used for Stage 2 when you click Run below.
          Skip this if <code>battery_lookup_dataset.csv</code> is already up to date.
        </p>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
          <label style={{
            display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
            padding: '0.45rem 0.9rem', borderRadius: 8, border: '1px solid #d1d5db',
            background: 'var(--adm-input-bg)', cursor: 'pointer', fontSize: '0.78rem', color: 'var(--adm-text-1)',
          }}>
            <CloudArrowUpIcon style={{ width: 14, height: 14 }} />
            {crspFile ? crspFile.name : 'Choose .xlsx file'}
            <input type="file" accept=".xlsx,.xls" style={{ display: 'none' }}
              onChange={e => { setCrspFile(e.target.files?.[0] ?? null); setCrspUploadedPath(null); setCrspUploadError(null) }} />
          </label>
          {crspFile && !crspUploadedPath && (
            <button
              disabled={crspUploadLoading}
              onClick={async () => {
                setCrspUploadLoading(true); setCrspUploadError(null)
                try {
                  const r = await crspUpload(crspFile!)
                  setCrspUploadedPath(r.file_path)
                } catch (e) { setCrspUploadError(e instanceof Error ? e.message : 'Upload failed') }
                finally { setCrspUploadLoading(false) }
              }}
              style={{ padding: '0.45rem 0.9rem', borderRadius: 8, border: 'none', background: '#3b82f6', color: '#fff', cursor: crspUploadLoading ? 'not-allowed' : 'pointer', fontSize: '0.78rem', fontWeight: 600, opacity: crspUploadLoading ? 0.7 : 1 }}>
              {crspUploadLoading ? 'Uploading…' : 'Upload'}
            </button>
          )}
          {crspUploadedPath && (
            <span style={{ fontSize: '0.7rem', color: '#15803d', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 6, padding: '0.3rem 0.6rem' }}>
              ✓ Uploaded — will be used for Stage 2
            </span>
          )}
          {crspUploadError && (
            <span style={{ fontSize: '0.7rem', color: '#dc2626' }}>{crspUploadError}</span>
          )}
        </div>
      </div>

      {/* Run controls */}
      <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center', flexWrap: 'wrap' }}>
        {(isIdle || isDone || isError || status?.status === 'cancelled') && (
          <button
            onClick={handleRun}
            disabled={runLoading}
            style={{
              display: 'flex', alignItems: 'center', gap: '0.45rem',
              fontSize: '0.82rem', fontWeight: 700,
              padding: '0.6rem 1.2rem', borderRadius: 10, border: 'none',
              cursor: runLoading ? 'not-allowed' : 'pointer',
              background: runLoading ? '#e2e4e9' : R,
              color: runLoading ? 'rgba(107,114,128,0.7)' : '#fff',
            }}
          >
            <PlayIcon style={{ width: 14, height: 14 }} />
            {runLoading ? 'Starting…' : 'Run CRSP Pipeline'}
          </button>
        )}

        {isActive && (
          <>
            <button
              onClick={() => handleAction(status?.status === 'paused' ? 'resume' : 'pause')}
              disabled={action !== null}
              style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.78rem', fontWeight: 700, padding: '0.55rem 1rem', borderRadius: 10, border: '1px solid #e2e4e9', background: 'var(--adm-card-bg)', cursor: 'pointer' }}
            >
              {status?.status === 'paused' ? <PlayIcon style={{ width: 13, height: 13 }} /> : <PauseIcon style={{ width: 13, height: 13 }} />}
              {action === 'pause' ? 'Pausing…' : action === 'resume' ? 'Resuming…' : status?.status === 'paused' ? 'Resume' : 'Pause'}
            </button>
            <button
              onClick={() => handleAction('cancel')}
              disabled={action !== null}
              style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.78rem', fontWeight: 700, padding: '0.55rem 1rem', borderRadius: 10, border: `1px solid ${R}`, background: '#fff5f5', color: R, cursor: 'pointer' }}
            >
              <StopIcon style={{ width: 13, height: 13 }} />
              {action === 'cancel' ? 'Cancelling…' : 'Cancel'}
            </button>
          </>
        )}

        {stagingAvailable && (
          <button
            onClick={() => setShowStaging(s => !s)}
            style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.78rem', fontWeight: 700, padding: '0.55rem 1rem', borderRadius: 10, border: '1px solid #e2e4e9', background: showStaging ? '#fffbeb' : 'var(--adm-card-bg)', cursor: 'pointer' }}
          >
            <ArchiveBoxIcon style={{ width: 13, height: 13 }} />
            {showStaging ? 'Hide Staging' : 'Review Staged Rows'}
          </button>
        )}
      </div>

      {actionError && (
        <div style={{ fontSize: '0.75rem', color: R, background: '#fff5f5', border: '1px solid #fca5a5', borderRadius: 8, padding: '0.5rem 0.75rem' }}>
          {actionError}
        </div>
      )}

      {/* Progress */}
      {isActive && status && (
        <div style={{ ...CARD, padding: '1rem 1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
            <span style={{ fontSize: '0.78rem', fontWeight: 700 }}>
              {status.status === 'paused' ? '⏸ Paused' : `Enriching — ${status.current_make ?? ''} ${status.current_model ?? ''}`}
            </span>
            <span style={{ fontSize: '0.72rem', color: '#6b7280' }}>
              {status.processed_models} / {status.total_models || '?'} pairs
            </span>
          </div>
          {status.total_models > 0 && (
            <div style={{ width: '100%', background: '#e2e4e9', borderRadius: 99, height: 6, overflow: 'hidden', marginBottom: '0.75rem' }}>
              <div style={{ width: `${pct}%`, background: status.status === 'paused' ? '#f59e0b' : R, height: '100%', borderRadius: 99, transition: 'width 0.4s' }} />
            </div>
          )}
          {/* Source breakdown */}
          {Object.keys(status.source_counts).length > 0 && (
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
              {Object.entries(status.source_counts).map(([src, count]) => (
                <span key={src} style={{ fontSize: '0.65rem', padding: '0.15rem 0.5rem', borderRadius: 99, background: '#f3f4f6', color: '#374151', fontWeight: 700 }}>
                  {SOURCE_LABELS[src] ?? src}: {count}
                </span>
              ))}
            </div>
          )}
          <LogPanel lines={status.logs} />
        </div>
      )}

      {/* Finished status */}
      {(isDone || status?.status === 'cancelled' || isError) && status && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: '0.6rem',
          padding: '0.55rem 1rem', background: 'var(--adm-card-bg)',
          border: '1px solid var(--adm-sep)', borderRadius: 99,
          fontSize: '0.75rem', fontWeight: 600,
          color: isError ? R : isDone ? '#15803d' : '#b45309',
        }}>
          {isError
            ? <><ExclamationCircleIcon style={{ width: 14, height: 14 }} /> Pipeline error — {status.error_detail}</>
            : isDone
            ? <><CheckCircleIcon style={{ width: 14, height: 14 }} /> Enrichment complete — {status.enriched_rows?.toLocaleString() ?? 0} rows staged for review</>
            : <><ExclamationCircleIcon style={{ width: 14, height: 14 }} /> Pipeline cancelled — partial results staged for review</>
          }
        </div>
      )}

      {/* Stage pipeline diagram */}
      <div style={{ ...CARD, padding: '1.25rem 1.25rem 1rem' }}>
        <h3 style={{ margin: '0 0 1rem', fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.8)' }}>
          Pipeline Stages
        </h3>
        <div>
          {CRSP_STAGES.map((stage, idx) => (
            <StageCard
              key={stage.id}
              stage={stage}
              status={getStageStatus(stage.id)}
              index={idx}
              total={CRSP_STAGES.length}
            />
          ))}
        </div>
      </div>

      {/* Commit result */}
      {commitResult && (
        <div style={{ fontSize: '0.75rem', color: '#15803d', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8, padding: '0.6rem 0.9rem' }}>
          ✓ Committed to vehicle_years — v{commitResult.version_number}: {commitResult.committed} added, {commitResult.updated} updated, {commitResult.conflict_kept} conflicts kept.
        </div>
      )}

      {/* Staging review panel */}
      {showStaging && (
        <CrspStagingPanel
          key={stagingKey}
          onCommit={result => { setCommitResult(result); setShowStaging(false); setStagingKey(k => k + 1) }}
          onDiscard={() => { setShowStaging(false); setStagingKey(k => k + 1) }}
        />
      )}

      {/* Version history */}
      <CrspVersionHistoryPanel />

      {/* DB stats */}
      <CrspStatsPanel />
    </div>
  )
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
            <div style={{ fontSize: '1.05rem', fontWeight: 800, color: 'rgba(17,24,39,0.88)' }}>Vehicle Dataset Pipeline</div>
            <div style={{ fontSize: '0.78rem', color: 'rgba(107,114,128,0.85)', marginTop: '0.2rem' }}>
              Run the CRSP pipeline to clean, enrich, and commit vehicle year data — or run web validation to find battery matches online.
            </div>
          </div>
        </div>

        {/* Dataset tabs */}
        <div style={{ ...CARD, padding: '1.25rem 1.5rem' }}>
          {/* Tab switcher */}
          <div style={{ display: 'flex', gap: '0.5rem', background: 'var(--adm-subtle-bg)', padding: '0.3rem', borderRadius: 99, width: 'fit-content', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
            <button style={tabStyle('crsp')} onClick={() => setActiveTab('crsp')}>
              <TableCellsIcon style={{ width: 14, height: 14 }} /> CRSP Pipeline
            </button>
            <button style={tabStyle('webvalidate')} onClick={() => setActiveTab('webvalidate')}>
              <GlobeAltIcon style={{ width: 14, height: 14 }} /> Web Validate
            </button>
          </div>

          {activeTab === 'crsp' ? (
            <CrspTab />
          ) : (
            <WebValidateTab />
          )}
        </div>

      </main>
    </AdminLayout>
  )
}
