import { useState, useEffect, useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { fetchSessions, revokeSession, AdminAuthError, type SessionEntry } from '@/lib/adminApi'
import { Toaster, useToast } from '@/components/Notification'
import { ArrowPathIcon, ShieldCheckIcon, ExclamationCircleIcon } from '@heroicons/react/20/solid'

// ── Design tokens (matching dashboard) ───────────────────────────────────────
const R = '#CC0000'
const BG = 'linear-gradient(160deg, #f4f5f7 0%, #eef0f4 100%)'
const CARD: React.CSSProperties = {
  background: '#ffffff',
  borderRadius: '14px',
  border: '1px solid #e2e4e9',
  boxShadow: '0 2px 12px rgba(0,0,0,0.07)',
  fontFamily: "'Segoe UI', system-ui, sans-serif",
}

export default function AdminSessions() {
  const navigate = useNavigate()
  const { toasts, push, dismiss } = useToast()
  const [sessions, setSessions] = useState<SessionEntry[]>([])
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState<string | null>(null)
  const [revoking, setRevoking] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await fetchSessions()
      setSessions(r.sessions)
    } catch (err) {
      if (err instanceof AdminAuthError) {
        navigate('/admin/login', { replace: true })
        return
      }
      setError(err instanceof Error ? err.message : 'Failed to load sessions')
    } finally {
      setLoading(false)
    }
  }, [navigate])

  useEffect(() => { load() }, [load])

  async function handleRevoke(id: number, ipAddress: string | null) {
    setRevoking(id)
    try {
      await revokeSession(id)
      push('success', 'Session revoked', `Session from ${ipAddress ?? 'unknown IP'} has been terminated`)
      await load()
    } catch (err) {
      if (err instanceof AdminAuthError) {
        navigate('/admin/login', { replace: true })
        return
      }
      push('error', 'Revoke failed', err instanceof Error ? err.message : 'Could not revoke session')
    } finally {
      setRevoking(null)
    }
  }

  function fmt(iso: string) { return new Date(iso).toLocaleString() }

  const activeSessions  = sessions.filter(s => !s.expired)
  const expiredSessions = sessions.filter(s =>  s.expired)

  return (
    <div style={{ minHeight: '100vh', background: BG, fontFamily: "'Segoe UI', system-ui, sans-serif" }}>
      <Toaster items={toasts} onDismiss={dismiss} />

      {/* Header */}
      <header style={{ background: '#fff', borderBottom: '1px solid #e2e4e9', boxShadow: '0 1px 6px rgba(0,0,0,0.06)', padding: '0 2rem', height: '60px', display: 'flex', alignItems: 'center', gap: '1rem', position: 'sticky', top: 0, zIndex: 50 }}>
        <Link to="/admin/dashboard" style={{ fontSize: '0.82rem', color: 'rgba(107,114,128,0.85)', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
          ← Dashboard
        </Link>
        <div style={{ width: 1, height: 20, background: '#e2e4e9' }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <ShieldCheckIcon style={{ width: 16, height: 16, color: R }} />
          <span style={{ fontSize: '1rem', fontWeight: 700, color: 'rgba(17,24,39,0.88)' }}>Session Management</span>
        </div>
        <button
          onClick={load}
          disabled={loading}
          style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', fontWeight: 600, color: R, background: '#fff5f5', border: '1px solid #f5c6c6', padding: '0.4rem 0.9rem', borderRadius: '8px', cursor: 'pointer', opacity: loading ? 0.6 : 1 }}
        >
          <ArrowPathIcon style={{ width: 13, height: 13, animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </header>

      <main style={{ maxWidth: '900px', margin: '0 auto', padding: '2rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>

        {error && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', borderRadius: '10px', background: '#fff5f5', border: '1px solid #f5c6c6', padding: '0.75rem 1rem', fontSize: '0.82rem', color: R }}>
            <ExclamationCircleIcon style={{ width: 15, height: 15 }} /> {error}
          </div>
        )}

        {/* Summary strip */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
          <div style={{ ...CARD, padding: '1rem 1.25rem', borderTop: `3px solid ${R}` }}>
            <div style={{ fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.8)', marginBottom: '0.4rem' }}>Active Sessions</div>
            <div style={{ fontSize: '2rem', fontWeight: 800, color: R, lineHeight: 1 }}>{loading ? '—' : activeSessions.length}</div>
          </div>
          <div style={{ ...CARD, padding: '1rem 1.25rem', borderTop: '3px solid #e2e4e9' }}>
            <div style={{ fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.8)', marginBottom: '0.4rem' }}>Expired Sessions</div>
            <div style={{ fontSize: '2rem', fontWeight: 800, color: 'rgba(107,114,128,0.7)', lineHeight: 1 }}>{loading ? '—' : expiredSessions.length}</div>
          </div>
        </div>

        {/* Sessions table */}
        <div style={{ ...CARD, overflow: 'hidden' }}>
          <div style={{ padding: '1rem 1.5rem', borderBottom: '1px solid #e2e4e9', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'rgba(17,24,39,0.8)' }}>All Sessions</span>
            <span style={{ fontSize: '0.72rem', color: 'rgba(107,114,128,0.7)' }}>{sessions.length} total</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
              <thead>
                <tr style={{ background: '#f8f9fb' }}>
                  {['ID', 'IP Address', 'Created', 'Expires', 'Status', 'Action'].map(h => (
                    <th key={h} style={{ padding: '0.7rem 1rem', textAlign: 'left', fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'rgba(107,114,128,0.8)', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr>
                    <td colSpan={6} style={{ padding: '2.5rem', textAlign: 'center', color: 'rgba(107,114,128,0.6)', fontSize: '0.82rem' }}>
                      Loading sessions…
                    </td>
                  </tr>
                )}
                {!loading && sessions.length === 0 && !error && (
                  <tr>
                    <td colSpan={6} style={{ padding: '2.5rem', textAlign: 'center', color: 'rgba(107,114,128,0.6)', fontSize: '0.82rem' }}>
                      No sessions found
                    </td>
                  </tr>
                )}
                {!loading && sessions.map((s, i) => (
                  <tr key={s.id} style={{ borderTop: i > 0 ? '1px solid #f0f1f4' : 'none', background: s.expired ? '#fafafa' : '#fff' }}
                    onMouseEnter={e => (e.currentTarget.style.background = s.expired ? '#f5f5f5' : '#fff8f8')}
                    onMouseLeave={e => (e.currentTarget.style.background = s.expired ? '#fafafa' : '#fff')}
                  >
                    <td style={{ padding: '0.75rem 1rem', fontFamily: 'monospace', fontSize: '0.75rem', color: 'rgba(107,114,128,0.9)' }}>#{s.id}</td>
                    <td style={{ padding: '0.75rem 1rem', fontFamily: 'monospace', fontSize: '0.75rem', color: 'rgba(17,24,39,0.7)' }}>{s.ip_address ?? '—'}</td>
                    <td style={{ padding: '0.75rem 1rem', fontSize: '0.75rem', color: 'rgba(107,114,128,0.8)', whiteSpace: 'nowrap' }}>{fmt(s.created_at)}</td>
                    <td style={{ padding: '0.75rem 1rem', fontSize: '0.75rem', color: s.expired ? 'rgba(107,114,128,0.6)' : 'rgba(107,114,128,0.8)', whiteSpace: 'nowrap' }}>{fmt(s.expires_at)}</td>
                    <td style={{ padding: '0.75rem 1rem' }}>
                      {s.expired ? (
                        <span style={{ display: 'inline-block', padding: '0.2rem 0.65rem', borderRadius: '99px', background: '#f1f2f4', color: 'rgba(107,114,128,0.8)', fontSize: '0.7rem', fontWeight: 600 }}>Expired</span>
                      ) : (
                        <span style={{ display: 'inline-block', padding: '0.2rem 0.65rem', borderRadius: '99px', background: '#f0fdf4', color: '#15803d', border: '1px solid #bbf7d0', fontSize: '0.7rem', fontWeight: 600 }}>● Active</span>
                      )}
                    </td>
                    <td style={{ padding: '0.75rem 1rem' }}>
                      {!s.expired && (
                        <button
                          onClick={() => handleRevoke(s.id, s.ip_address)}
                          disabled={revoking === s.id}
                          style={{ fontSize: '0.75rem', fontWeight: 600, color: revoking === s.id ? 'rgba(107,114,128,0.5)' : R, background: revoking === s.id ? 'transparent' : '#fff5f5', border: `1px solid ${revoking === s.id ? '#e2e4e9' : '#f5c6c6'}`, padding: '0.25rem 0.7rem', borderRadius: '6px', cursor: revoking === s.id ? 'not-allowed' : 'pointer', transition: 'all 0.15s' }}
                        >
                          {revoking === s.id ? 'Revoking…' : 'Revoke'}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </main>

      <footer style={{ textAlign: 'center', padding: '1.5rem', fontSize: '0.7rem', color: 'rgba(107,114,128,0.5)' }}>
        © 2026 Chloride Exide · Battery Finder Admin
      </footer>
    </div>
  )
}
