import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  fetchTestSessions, revokeTestSession, fetchTestUsers,
  AdminAuthError,
  type TestSessionEntry, type TestUserEntry,
} from '@/lib/adminApi'
import { Toaster, useToast } from '@/components/Notification'
import {
  ArrowPathIcon, UserGroupIcon, ShieldExclamationIcon,
} from '@heroicons/react/20/solid'
import AdminLayout from '@/components/admin/AdminLayout'

const R = '#CC0000'
const CARD: React.CSSProperties = {
  background: '#ffffff',
  borderRadius: '14px',
  border: '1px solid #e2e4e9',
  boxShadow: '0 2px 12px rgba(0,0,0,0.07)',
  fontFamily: "'Segoe UI', system-ui, sans-serif",
}

type TabId = 'sessions' | 'users'

export default function AdminTestSessions() {
  const navigate = useNavigate()
  const { toasts, push, dismiss } = useToast()
  const [tab, setTab]             = useState<TabId>('sessions')
  const [sessions, setSessions]   = useState<TestSessionEntry[]>([])
  const [users, setUsers]         = useState<TestUserEntry[]>([])
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState<string | null>(null)
  const [revoking, setRevoking]   = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [s, u] = await Promise.all([fetchTestSessions(), fetchTestUsers()])
      setSessions(s.sessions)
      setUsers(u.users)
    } catch (err) {
      if (err instanceof AdminAuthError) { navigate('/admin/login', { replace: true }); return }
      setError(err instanceof Error ? err.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [navigate])

  useEffect(() => { load() }, [load])

  async function handleRevoke(id: number, username: string) {
    setRevoking(id)
    try {
      await revokeTestSession(id)
      push('success', 'Session revoked', `${username}'s session has been terminated`)
      await load()
    } catch (err) {
      if (err instanceof AdminAuthError) { navigate('/admin/login', { replace: true }); return }
      push('error', 'Revoke failed', err instanceof Error ? err.message : 'Could not revoke session')
    } finally {
      setRevoking(null)
    }
  }

  function fmt(iso: string | null) { return iso ? new Date(iso).toLocaleString() : '—' }

  const activeSessions  = sessions.filter(s => !s.expired)
  const expiredSessions = sessions.filter(s =>  s.expired)

  return (
    <AdminLayout>
      <Toaster items={toasts} onDismiss={dismiss} />

      {/* Header */}
      <header style={{
        background: '#fff', borderBottom: '1px solid #e2e4e9',
        boxShadow: '0 1px 6px rgba(0,0,0,0.06)', padding: '0 2rem', height: '60px',
        display: 'flex', alignItems: 'center', gap: '1rem', position: 'sticky', top: 0, zIndex: 50,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <UserGroupIcon style={{ width: 16, height: 16, color: R }} />
          <span style={{ fontSize: '1rem', fontWeight: 700, color: 'rgba(17,24,39,0.88)' }}>
            Test Users &amp; Sessions
          </span>
        </div>
        {/* Stats chips */}
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginLeft: '0.5rem' }}>
          <span style={{ fontSize: '0.72rem', fontWeight: 600, padding: '0.25rem 0.65rem', borderRadius: 20, background: '#f0fdf4', color: '#15803d', border: '1px solid #bbf7d0' }}>
            {activeSessions.length} active session{activeSessions.length !== 1 ? 's' : ''}
          </span>
          <span style={{ fontSize: '0.72rem', fontWeight: 600, padding: '0.25rem 0.65rem', borderRadius: 20, background: '#f9fafb', color: '#6b7280', border: '1px solid #e2e4e9' }}>
            {users.length} user{users.length !== 1 ? 's' : ''}
          </span>
        </div>
        <button
          onClick={load}
          disabled={loading}
          style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', fontWeight: 600, color: R, background: '#fff5f5', border: '1px solid #f5c6c6', padding: '0.4rem 0.9rem', borderRadius: '8px', cursor: 'pointer', opacity: loading ? 0.6 : 1 }}
        >
          <ArrowPathIcon style={{ width: 13, height: 13, animation: loading ? 'spin 0.8s linear infinite' : 'none' }} />
          Refresh
        </button>
      </header>

      {/* Main */}
      <main style={{ padding: '1.75rem 2rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        {error && (
          <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 10, padding: '0.75rem 1rem', color: '#b91c1c', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <ShieldExclamationIcon style={{ width: 16, height: 16 }} />
            {error}
          </div>
        )}

        {/* Tab switcher */}
        <div style={{ display: 'flex', gap: '0.5rem', borderBottom: '1px solid #e2e4e9', paddingBottom: '0.1rem' }}>
          {(['sessions', 'users'] as TabId[]).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                padding: '0.45rem 1rem',
                border: 'none',
                borderBottom: tab === t ? `2px solid ${R}` : '2px solid transparent',
                background: 'transparent',
                fontWeight: tab === t ? 700 : 500,
                color: tab === t ? R : '#6b7280',
                fontSize: '0.85rem',
                cursor: 'pointer',
                textTransform: 'capitalize',
              }}
            >
              {t === 'sessions' ? `Sessions (${sessions.length})` : `Users (${users.length})`}
            </button>
          ))}
        </div>

        {/* Sessions tab */}
        {tab === 'sessions' && (
          <>
            {/* Active */}
            <SectionCard title={`Active (${activeSessions.length})`} color="#15803d" bg="#f0fdf4">
              {activeSessions.length === 0
                ? <EmptyRow text="No active sessions" />
                : <SessionTable rows={activeSessions} revoking={revoking} onRevoke={handleRevoke} fmt={fmt} />
              }
            </SectionCard>

            {/* Expired */}
            {expiredSessions.length > 0 && (
              <SectionCard title={`Expired (${expiredSessions.length})`} color="#9ca3af" bg="#f9fafb">
                <SessionTable rows={expiredSessions} revoking={null} onRevoke={null} fmt={fmt} dimmed />
              </SectionCard>
            )}
          </>
        )}

        {/* Users tab */}
        {tab === 'users' && (
          <div style={{ ...CARD, overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.83rem' }}>
              <thead>
                <tr style={{ background: '#f9fafb', borderBottom: '1px solid #e2e4e9' }}>
                  {['ID', 'Username', 'Email', 'Joined', 'Active Sessions', 'Status'].map(h => (
                    <th key={h} style={{ padding: '0.6rem 1rem', textAlign: 'left', fontWeight: 700, color: '#374151', fontSize: '0.76rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {users.length === 0
                  ? <tr><td colSpan={6} style={{ padding: '2rem', textAlign: 'center', color: '#9ca3af' }}>No test users yet</td></tr>
                  : users.map((u, i) => (
                    <tr key={u.id} style={{ borderBottom: i < users.length - 1 ? '1px solid #f3f4f6' : undefined }}>
                      <td style={{ padding: '0.7rem 1rem', color: '#9ca3af' }}>{u.id}</td>
                      <td style={{ padding: '0.7rem 1rem', fontWeight: 600, color: '#111827' }}>{u.username}</td>
                      <td style={{ padding: '0.7rem 1rem', color: '#6b7280' }}>{u.email ?? '—'}</td>
                      <td style={{ padding: '0.7rem 1rem', color: '#6b7280' }}>{fmt(u.created_at)}</td>
                      <td style={{ padding: '0.7rem 1rem' }}>
                        <span style={{ fontWeight: 700, color: u.active_sessions > 0 ? '#15803d' : '#9ca3af' }}>
                          {u.active_sessions}
                        </span>
                      </td>
                      <td style={{ padding: '0.7rem 1rem' }}>
                        <span style={{
                          padding: '0.2rem 0.55rem', borderRadius: 20, fontSize: '0.72rem', fontWeight: 700,
                          background: u.is_active ? '#f0fdf4' : '#fef2f2',
                          color: u.is_active ? '#15803d' : '#b91c1c',
                          border: `1px solid ${u.is_active ? '#bbf7d0' : '#fecaca'}`,
                        }}>
                          {u.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                    </tr>
                  ))
                }
              </tbody>
            </table>
          </div>
        )}
      </main>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg) } }
      `}</style>
    </AdminLayout>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────

function SectionCard({ title, color, bg, children }: {
  title: string; color: string; bg: string; children: React.ReactNode
}) {
  return (
    <div style={{ ...CARD, overflow: 'hidden' }}>
      <div style={{ padding: '0.7rem 1rem', borderBottom: '1px solid #e2e4e9', background: bg, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <span style={{ fontSize: '0.78rem', fontWeight: 700, color, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          {title}
        </span>
      </div>
      {children}
    </div>
  )
}

function EmptyRow({ text }: { text: string }) {
  return (
    <div style={{ padding: '1.5rem', textAlign: 'center', color: '#9ca3af', fontSize: '0.85rem' }}>
      {text}
    </div>
  )
}

function SessionTable({ rows, revoking, onRevoke, fmt, dimmed = false }: {
  rows: TestSessionEntry[]
  revoking: number | null
  onRevoke: ((id: number, username: string) => void) | null
  fmt: (s: string | null) => string
  dimmed?: boolean
}) {
  const R = '#CC0000'
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.83rem', opacity: dimmed ? 0.7 : 1 }}>
      <thead>
        <tr style={{ background: '#f9fafb', borderBottom: '1px solid #e2e4e9' }}>
          {['User', 'IP Address', 'User Agent', 'Created', 'Last Seen', 'Expires', ''].map(h => (
            <th key={h} style={{ padding: '0.6rem 1rem', textAlign: 'left', fontWeight: 700, color: '#374151', fontSize: '0.76rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((s, i) => (
          <tr key={s.id} style={{ borderBottom: i < rows.length - 1 ? '1px solid #f3f4f6' : undefined }}>
            <td style={{ padding: '0.7rem 1rem', fontWeight: 600, color: '#111827' }}>{s.username}</td>
            <td style={{ padding: '0.7rem 1rem', color: '#6b7280', fontFamily: 'monospace' }}>{s.ip_address ?? '—'}</td>
            <td style={{ padding: '0.7rem 1rem', color: '#9ca3af', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              title={s.user_agent ?? undefined}>
              {s.user_agent ? s.user_agent.slice(0, 48) + (s.user_agent.length > 48 ? '…' : '') : '—'}
            </td>
            <td style={{ padding: '0.7rem 1rem', color: '#6b7280' }}>{fmt(s.created_at)}</td>
            <td style={{ padding: '0.7rem 1rem', color: '#6b7280' }}>{fmt(s.last_seen_at)}</td>
            <td style={{ padding: '0.7rem 1rem', color: '#6b7280' }}>{fmt(s.expires_at)}</td>
            <td style={{ padding: '0.7rem 1rem' }}>
              {onRevoke && !s.expired && (
                <button
                  onClick={() => onRevoke(s.id, s.username)}
                  disabled={revoking === s.id}
                  style={{
                    fontSize: '0.75rem', fontWeight: 600, padding: '0.3rem 0.7rem',
                    borderRadius: 6, border: `1px solid ${R}`, background: '#fff5f5',
                    color: R, cursor: 'pointer', opacity: revoking === s.id ? 0.5 : 1,
                  }}
                >
                  {revoking === s.id ? 'Revoking…' : 'Revoke'}
                </button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
