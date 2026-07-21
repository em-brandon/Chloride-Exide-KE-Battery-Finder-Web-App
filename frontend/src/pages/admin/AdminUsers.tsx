import { useState, useEffect, useCallback, type FormEvent } from 'react'
import {
  fetchAdminUsers, createAdminUser, updateOwnEmail, deleteAdminUser, generateResetLink,
  fetchAdminAccountAuditLog, adminMe, AdminAuthError,
  type AdminUserRow, type AdminAccountAuditEntry,
} from '@/lib/adminApi'
import { Toaster, useToast } from '@/components/Notification'
import { UsersIcon, PlusIcon, ArrowPathIcon, XMarkIcon, KeyIcon } from '@heroicons/react/20/solid'
import AdminLayout from '@/components/admin/AdminLayout'
import { useNavigate } from 'react-router-dom'

const R = '#CC0000'
const CARD: React.CSSProperties = {
  background: 'var(--adm-card-bg)',
  borderRadius: '14px',
  border: '1px solid var(--adm-card-border)',
  boxShadow: 'var(--adm-card-shadow)',
  fontFamily: "'Segoe UI', system-ui, sans-serif",
}
const INPUT: React.CSSProperties = {
  width: '100%', borderRadius: '8px', border: '1px solid var(--adm-input-border)',
  background: 'var(--adm-input-bg)', color: 'var(--adm-text-1)', padding: '0.45rem 0.75rem',
  fontSize: '0.85rem', fontFamily: "'Segoe UI', system-ui, sans-serif", outline: 'none', boxSizing: 'border-box',
}

function fmt(iso: string) { return new Date(iso).toLocaleString() }

// ── Add Admin modal ──────────────────────────────────────────────────────
function AddAdminModal({ onSave, onCancel }: { onSave: (payload: { username: string; password: string; email?: string }) => Promise<void>; onCancel: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail]       = useState('')
  const [err, setErr]           = useState<string | null>(null)
  const [busy, setBusy]         = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setErr(null)
    setBusy(true)
    try {
      await onSave({ username, password, email: email || undefined })
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Save failed')
      setBusy(false)
    }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: '1rem' }}>
      <div style={{ ...CARD, padding: '1.75rem', width: '100%', maxWidth: '400px', maxHeight: '90vh', overflow: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
          <h2 style={{ fontSize: '0.95rem', fontWeight: 800, color: 'var(--adm-text-1)', margin: 0 }}>Add Admin</h2>
          <button onClick={onCancel} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'rgba(107,114,128,0.6)', padding: '2px' }}>
            <XMarkIcon style={{ width: 18, height: 18 }} />
          </button>
        </div>
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
          {err && (
            <div style={{ background: '#fff5f5', border: '1px solid #f5c6c6', borderRadius: '8px', padding: '0.6rem 0.85rem', fontSize: '0.8rem', color: R }}>
              {err}
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
            <label style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--adm-text-3)' }}>Username</label>
            <input type="text" required value={username} onChange={e => setUsername(e.target.value)} style={INPUT} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
            <label style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--adm-text-3)' }}>Password</label>
            <input type="password" required minLength={8} value={password} onChange={e => setPassword(e.target.value)} style={INPUT} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
            <label style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--adm-text-3)' }}>Email (optional)</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} style={INPUT} />
          </div>
          <div style={{ display: 'flex', gap: '0.6rem', paddingTop: '0.25rem' }}>
            <button type="submit" disabled={busy} style={{ flex: 1, background: busy ? '#e88' : R, color: '#fff', border: 'none', borderRadius: '8px', padding: '0.55rem', fontSize: '0.85rem', fontWeight: 700, cursor: busy ? 'not-allowed' : 'pointer' }}>
              {busy ? 'Saving…' : 'Save'}
            </button>
            <button type="button" onClick={onCancel} style={{ flex: 1, background: 'var(--adm-subtle-bg)', color: 'var(--adm-text-1)', border: '1px solid var(--adm-sep)', borderRadius: '8px', padding: '0.55rem', fontSize: '0.85rem', fontWeight: 600, cursor: 'pointer' }}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Reset link modal ─────────────────────────────────────────────────────
function ResetLinkModal({ url, onClose }: { url: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: '1rem' }}>
      <div style={{ ...CARD, padding: '1.75rem', width: '100%', maxWidth: '460px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
          <h2 style={{ fontSize: '0.95rem', fontWeight: 800, color: 'var(--adm-text-1)', margin: 0 }}>Reset link generated</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'rgba(107,114,128,0.6)', padding: '2px' }}>
            <XMarkIcon style={{ width: 18, height: 18 }} />
          </button>
        </div>
        <p style={{ fontSize: '0.8rem', color: 'var(--adm-text-2)', marginBottom: '0.75rem' }}>
          This link expires in 1 hour and can only be used once. Share it with the admin through a trusted channel (Slack, in person) — it is not emailed automatically.
        </p>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <input readOnly value={url} style={{ ...INPUT, fontFamily: 'monospace', fontSize: '0.75rem' }} onFocus={e => e.currentTarget.select()} />
          <button
            onClick={() => { navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
            style={{ flexShrink: 0, background: copied ? '#16a34a' : R, color: '#fff', border: 'none', borderRadius: '8px', padding: '0.45rem 0.9rem', fontSize: '0.8rem', fontWeight: 700, cursor: 'pointer' }}
          >
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────
export default function AdminUsers() {
  const navigate = useNavigate()
  const { toasts, push, dismiss } = useToast()
  const [users, setUsers]     = useState<AdminUserRow[]>([])
  const [ownUsername, setOwnUsername] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [resetLinkUrl, setResetLinkUrl] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [editingEmail, setEditingEmail] = useState<{ id: number; value: string } | null>(null)

  const [auditLog, setAuditLog] = useState<AdminAccountAuditEntry[]>([])
  const [auditLoading, setAuditLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [u, me] = await Promise.all([fetchAdminUsers(), adminMe()])
      setUsers(u.users)
      setOwnUsername(me.username)
    } catch (err) {
      if (err instanceof AdminAuthError) { navigate('/admin/login', { replace: true }); return }
      setError(err instanceof Error ? err.message : 'Failed to load admin users')
    } finally {
      setLoading(false)
    }
  }, [navigate])

  const loadAudit = useCallback(async () => {
    setAuditLoading(true)
    try {
      const r = await fetchAdminAccountAuditLog(1, 50)
      setAuditLog(r.items)
    } catch {
      // Non-critical secondary panel — leave it empty on failure rather
      // than blocking the rest of the page.
    } finally {
      setAuditLoading(false)
    }
  }, [])

  useEffect(() => { load(); loadAudit() }, [load, loadAudit])

  async function handleAdd(payload: { username: string; password: string; email?: string }) {
    await createAdminUser(payload)
    setShowAdd(false)
    push('success', 'Admin created', `${payload.username} can now sign in`)
    load()
    loadAudit()
  }

  async function handleDelete(u: AdminUserRow) {
    if (!window.confirm(`Delete admin ${u.username}? This cannot be undone.`)) return
    setDeleting(u.id)
    try {
      await deleteAdminUser(u.id)
      push('success', 'Admin deleted', `${u.username} has been removed`)
      load()
      loadAudit()
    } catch (err) {
      push('error', 'Delete failed', err instanceof Error ? err.message : 'Could not delete admin')
    } finally {
      setDeleting(null)
    }
  }

  async function handleGenerateResetLink(u: AdminUserRow) {
    try {
      const r = await generateResetLink(u.id)
      const url = `${window.location.origin}/admin/reset-password?token=${r.token}`
      setResetLinkUrl(url)
      loadAudit()
    } catch (err) {
      push('error', 'Could not generate link', err instanceof Error ? err.message : 'Try again')
    }
  }

  async function handleSaveEmail() {
    if (!editingEmail) return
    try {
      await updateOwnEmail(editingEmail.id, editingEmail.value)
      push('success', 'Email updated')
      setEditingEmail(null)
      load()
    } catch (err) {
      push('error', 'Update failed', err instanceof Error ? err.message : 'Try again')
    }
  }

  return (
    <AdminLayout>
      <Toaster items={toasts} onDismiss={dismiss} />
      {showAdd && <AddAdminModal onSave={handleAdd} onCancel={() => setShowAdd(false)} />}
      {resetLinkUrl && <ResetLinkModal url={resetLinkUrl} onClose={() => setResetLinkUrl(null)} />}

      <header style={{ background: 'var(--adm-header-bg)', borderBottom: '1px solid var(--adm-sep)', boxShadow: '0 1px 6px rgba(0,0,0,0.06)', padding: '0 2rem', height: '60px', display: 'flex', alignItems: 'center', gap: '1rem', position: 'sticky', top: 0, zIndex: 50 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <UsersIcon style={{ width: 16, height: 16, color: R }} />
          <span style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--adm-text-1)' }}>Admin Users</span>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: '0.5rem' }}>
          <button onClick={() => { load(); loadAudit() }} disabled={loading} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', fontWeight: 600, color: R, background: '#fff5f5', border: '1px solid #f5c6c6', padding: '0.4rem 0.9rem', borderRadius: '8px', cursor: 'pointer', opacity: loading ? 0.6 : 1 }}>
            <ArrowPathIcon style={{ width: 13, height: 13 }} /> Refresh
          </button>
          <button onClick={() => setShowAdd(true)} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', fontWeight: 700, color: '#fff', background: R, border: 'none', padding: '0.4rem 0.9rem', borderRadius: '8px', cursor: 'pointer' }}>
            <PlusIcon style={{ width: 13, height: 13 }} /> Add Admin
          </button>
        </div>
      </header>

      <main style={{ maxWidth: '1000px', margin: '0 auto', padding: '2rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        {error && (
          <div style={{ background: '#fff5f5', border: '1px solid #f5c6c6', borderRadius: 10, padding: '0.75rem 1rem', fontSize: '0.82rem', color: R }}>
            {error}
          </div>
        )}

        <div style={{ ...CARD, overflow: 'hidden' }}>
          <div style={{ padding: '1rem 1.5rem', borderBottom: '1px solid var(--adm-sep)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--adm-text-1)' }}>Admins</span>
            <span style={{ fontSize: '0.72rem', color: 'var(--adm-text-2)' }}>{users.length} total</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
              <thead>
                <tr style={{ background: 'var(--adm-thead-bg)' }}>
                  {['Username', 'Email', 'Created', 'Status', 'Actions'].map(h => (
                    <th key={h} style={{ padding: '0.7rem 1rem', textAlign: 'left', fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--adm-text-2)', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={5} style={{ padding: '2.5rem', textAlign: 'center', color: 'var(--adm-text-2)', fontSize: '0.82rem' }}>Loading…</td></tr>
                )}
                {!loading && users.map((u, i) => {
                  const isSelf = u.username === ownUsername
                  const isEditingThisRow = editingEmail?.id === u.id
                  return (
                    <tr key={u.id} style={{ borderTop: i > 0 ? '1px solid var(--adm-row-border)' : 'none' }}>
                      <td style={{ padding: '0.75rem 1rem', fontWeight: 600, color: 'var(--adm-text-1)' }}>
                        {u.username} {isSelf && <span style={{ fontSize: '0.65rem', color: 'var(--adm-text-3)', fontWeight: 500 }}>(you)</span>}
                      </td>
                      <td style={{ padding: '0.75rem 1rem' }}>
                        {isEditingThisRow ? (
                          <div style={{ display: 'flex', gap: '0.3rem' }}>
                            <input
                              type="email" value={editingEmail.value} autoFocus
                              onChange={e => setEditingEmail({ id: u.id, value: e.target.value })}
                              style={{ ...INPUT, fontSize: '0.78rem', padding: '0.25rem 0.5rem' }}
                            />
                            <button onClick={handleSaveEmail} style={{ fontSize: '0.72rem', fontWeight: 700, color: '#15803d', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: '6px', padding: '0.2rem 0.5rem', cursor: 'pointer' }}>Save</button>
                            <button onClick={() => setEditingEmail(null)} style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--adm-text-2)', background: 'transparent', border: '1px solid var(--adm-sep)', borderRadius: '6px', padding: '0.2rem 0.5rem', cursor: 'pointer' }}>Cancel</button>
                          </div>
                        ) : (
                          <span style={{ color: u.email ? 'var(--adm-text-2)' : 'var(--adm-text-3)' }}>
                            {u.email ?? '— not set'}
                            {isSelf && (
                              <button
                                onClick={() => setEditingEmail({ id: u.id, value: u.email ?? '' })}
                                style={{ marginLeft: '0.5rem', fontSize: '0.68rem', fontWeight: 700, color: '#1d4ed8', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                              >
                                edit
                              </button>
                            )}
                          </span>
                        )}
                      </td>
                      <td style={{ padding: '0.75rem 1rem', color: 'var(--adm-text-2)', whiteSpace: 'nowrap', fontSize: '0.75rem' }}>{fmt(u.created_at)}</td>
                      <td style={{ padding: '0.75rem 1rem' }}>
                        {u.locked ? (
                          <span style={{ display: 'inline-block', padding: '0.15rem 0.55rem', borderRadius: '99px', background: '#fff5f5', color: R, border: '1px solid #f5c6c6', fontSize: '0.7rem', fontWeight: 700 }}>Locked</span>
                        ) : (
                          <span style={{ display: 'inline-block', padding: '0.15rem 0.55rem', borderRadius: '99px', background: '#f0fdf4', color: '#15803d', border: '1px solid #bbf7d0', fontSize: '0.7rem', fontWeight: 700 }}>Active</span>
                        )}
                      </td>
                      <td style={{ padding: '0.75rem 1rem' }}>
                        <div style={{ display: 'flex', gap: '0.4rem' }}>
                          <button
                            onClick={() => handleGenerateResetLink(u)}
                            title="Generate a password-reset link to share manually"
                            style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.72rem', fontWeight: 600, color: '#1d4ed8', background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: '6px', padding: '0.25rem 0.6rem', cursor: 'pointer' }}
                          >
                            <KeyIcon style={{ width: 11, height: 11 }} /> Reset Link
                          </button>
                          <button
                            onClick={() => handleDelete(u)}
                            disabled={isSelf || deleting === u.id}
                            title={isSelf ? "You can't delete your own account" : undefined}
                            style={{ fontSize: '0.72rem', fontWeight: 600, color: isSelf || deleting === u.id ? 'rgba(107,114,128,0.4)' : R, background: isSelf || deleting === u.id ? 'var(--adm-subtle-bg)' : '#fff5f5', border: `1px solid ${isSelf || deleting === u.id ? 'var(--adm-sep)' : '#f5c6c6'}`, borderRadius: '6px', padding: '0.25rem 0.6rem', cursor: isSelf || deleting === u.id ? 'not-allowed' : 'pointer' }}
                          >
                            {deleting === u.id ? '…' : 'Delete'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Activity / audit trail */}
        <div style={{ ...CARD, overflow: 'hidden' }}>
          <div style={{ padding: '1rem 1.5rem', borderBottom: '1px solid var(--adm-sep)' }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--adm-text-1)' }}>Activity</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
              <thead>
                <tr style={{ background: 'var(--adm-thead-bg)' }}>
                  {['Action', 'Actor', 'Target', 'When'].map(h => (
                    <th key={h} style={{ padding: '0.6rem 1rem', textAlign: 'left', fontSize: '0.62rem', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--adm-text-2)', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {auditLoading && (
                  <tr><td colSpan={4} style={{ padding: '2rem', textAlign: 'center', color: 'var(--adm-text-2)' }}>Loading…</td></tr>
                )}
                {!auditLoading && auditLog.length === 0 && (
                  <tr><td colSpan={4} style={{ padding: '2rem', textAlign: 'center', color: 'var(--adm-text-2)' }}>No activity yet</td></tr>
                )}
                {!auditLoading && auditLog.map((row, i) => (
                  <tr key={row.id} style={{ borderTop: i > 0 ? '1px solid var(--adm-row-border)' : 'none' }}>
                    <td style={{ padding: '0.6rem 1rem', color: 'var(--adm-text-1)', textTransform: 'capitalize' }}>{row.action.replace(/_/g, ' ')}</td>
                    <td style={{ padding: '0.6rem 1rem', color: 'var(--adm-text-2)' }}>{row.actor_username ?? '—'}</td>
                    <td style={{ padding: '0.6rem 1rem', color: 'var(--adm-text-2)' }}>{row.target_username}</td>
                    <td style={{ padding: '0.6rem 1rem', color: 'var(--adm-text-3)', whiteSpace: 'nowrap' }}>{fmt(row.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </AdminLayout>
  )
}
