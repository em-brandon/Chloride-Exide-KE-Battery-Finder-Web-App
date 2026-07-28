import { useState, useEffect, useCallback } from 'react'
import {
  createBackup, listBackups, getBackupLog, backupDownloadUrl, AdminAuthError,
  type BackupEntry, type BackupLogEntry,
} from '@/lib/adminApi'
import { Toaster, useToast } from '@/components/Notification'
import { CircleStackIcon, ArrowPathIcon, ArrowDownTrayIcon } from '@heroicons/react/20/solid'
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

function fmt(iso: string) { return new Date(iso).toLocaleString() }

function fmtSize(bytes: number | null) {
  if (bytes === null) return '—'
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function AdminBackups() {
  const navigate = useNavigate()
  const { toasts, push, dismiss } = useToast()
  const [backups, setBackups] = useState<BackupEntry[]>([])
  const [log, setLog] = useState<BackupLogEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [b, l] = await Promise.all([listBackups(), getBackupLog()])
      setBackups(b.backups)
      setLog(l.items)
    } catch (err) {
      if (err instanceof AdminAuthError) { navigate('/admin/login', { replace: true }); return }
      setError(err instanceof Error ? err.message : 'Failed to load backups')
    } finally {
      setLoading(false)
    }
  }, [navigate])

  useEffect(() => { load() }, [load])

  async function handleCreate() {
    setCreating(true)
    try {
      const r = await createBackup()
      push('success', 'Backup created', `${r.filename} (${fmtSize(r.size_bytes)})`)
      load()
    } catch (err) {
      push('error', 'Backup failed', err instanceof Error ? err.message : 'Try again')
    } finally {
      setCreating(false)
    }
  }

  return (
    <AdminLayout>
      <Toaster items={toasts} onDismiss={dismiss} />

      <header style={{ background: 'var(--adm-header-bg)', borderBottom: '1px solid var(--adm-sep)', boxShadow: '0 1px 6px rgba(0,0,0,0.06)', padding: '0 2rem', height: '60px', display: 'flex', alignItems: 'center', gap: '1rem', position: 'sticky', top: 0, zIndex: 50 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <CircleStackIcon style={{ width: 16, height: 16, color: R }} />
          <span style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--adm-text-1)' }}>Database Backups</span>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: '0.5rem' }}>
          <button onClick={load} disabled={loading} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', fontWeight: 600, color: R, background: '#fff5f5', border: '1px solid #f5c6c6', padding: '0.4rem 0.9rem', borderRadius: '8px', cursor: 'pointer', opacity: loading ? 0.6 : 1 }}>
            <ArrowPathIcon style={{ width: 13, height: 13 }} /> Refresh
          </button>
          <button onClick={handleCreate} disabled={creating} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.75rem', fontWeight: 700, color: '#fff', background: creating ? '#e88' : R, border: 'none', padding: '0.4rem 0.9rem', borderRadius: '8px', cursor: creating ? 'not-allowed' : 'pointer' }}>
            {creating ? 'Backing up…' : 'Back Up Now'}
          </button>
        </div>
      </header>

      <main style={{ maxWidth: '1000px', margin: '0 auto', padding: '2rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        <div style={{ background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 10, padding: '0.75rem 1rem', fontSize: '0.78rem', color: '#1d4ed8' }}>
          Backs up the local Docker Postgres dev database via <code>pg_dump</code> into the repo's <code>backups/</code> folder — the newest 10 dumps are kept. This currently only works against the local Docker container; it is not yet wired up for production RDS.
        </div>

        {error && (
          <div style={{ background: '#fff5f5', border: '1px solid #f5c6c6', borderRadius: 10, padding: '0.75rem 1rem', fontSize: '0.82rem', color: R }}>
            {error}
          </div>
        )}

        <div style={{ ...CARD, overflow: 'hidden' }}>
          <div style={{ padding: '1rem 1.5rem', borderBottom: '1px solid var(--adm-sep)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--adm-text-1)' }}>Available Backups</span>
            <span style={{ fontSize: '0.72rem', color: 'var(--adm-text-2)' }}>{backups.length} total</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
              <thead>
                <tr style={{ background: 'var(--adm-thead-bg)' }}>
                  {['Filename', 'Size', 'Created', ''].map(h => (
                    <th key={h} style={{ padding: '0.7rem 1rem', textAlign: 'left', fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--adm-text-2)', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={4} style={{ padding: '2.5rem', textAlign: 'center', color: 'var(--adm-text-2)', fontSize: '0.82rem' }}>Loading…</td></tr>
                )}
                {!loading && backups.length === 0 && (
                  <tr><td colSpan={4} style={{ padding: '2.5rem', textAlign: 'center', color: 'var(--adm-text-2)', fontSize: '0.82rem' }}>No backups yet</td></tr>
                )}
                {!loading && backups.map((b, i) => (
                  <tr key={b.filename} style={{ borderTop: i > 0 ? '1px solid var(--adm-row-border)' : 'none' }}>
                    <td style={{ padding: '0.75rem 1rem', fontWeight: 600, color: 'var(--adm-text-1)', fontFamily: 'monospace', fontSize: '0.75rem' }}>{b.filename}</td>
                    <td style={{ padding: '0.75rem 1rem', color: 'var(--adm-text-2)' }}>{fmtSize(b.size_bytes)}</td>
                    <td style={{ padding: '0.75rem 1rem', color: 'var(--adm-text-2)', whiteSpace: 'nowrap', fontSize: '0.75rem' }}>{fmt(b.modified_at)}</td>
                    <td style={{ padding: '0.75rem 1rem' }}>
                      <a
                        href={backupDownloadUrl(b.filename)}
                        style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.72rem', fontWeight: 600, color: '#1d4ed8', background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: '6px', padding: '0.25rem 0.6rem', textDecoration: 'none' }}
                      >
                        <ArrowDownTrayIcon style={{ width: 11, height: 11 }} /> Download
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div style={{ ...CARD, overflow: 'hidden' }}>
          <div style={{ padding: '1rem 1.5rem', borderBottom: '1px solid var(--adm-sep)' }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--adm-text-1)' }}>Activity</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
              <thead>
                <tr style={{ background: 'var(--adm-thead-bg)' }}>
                  {['Filename', 'Status', 'Triggered By', 'When'].map(h => (
                    <th key={h} style={{ padding: '0.6rem 1rem', textAlign: 'left', fontSize: '0.62rem', fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--adm-text-2)', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {!loading && log.length === 0 && (
                  <tr><td colSpan={4} style={{ padding: '2rem', textAlign: 'center', color: 'var(--adm-text-2)' }}>No activity yet</td></tr>
                )}
                {log.map((row, i) => (
                  <tr key={row.id} style={{ borderTop: i > 0 ? '1px solid var(--adm-row-border)' : 'none' }}>
                    <td style={{ padding: '0.6rem 1rem', color: 'var(--adm-text-1)', fontFamily: 'monospace', fontSize: '0.72rem' }}>{row.filename || '—'}</td>
                    <td style={{ padding: '0.6rem 1rem' }}>
                      {row.status === 'success' ? (
                        <span style={{ display: 'inline-block', padding: '0.1rem 0.5rem', borderRadius: '99px', background: '#f0fdf4', color: '#15803d', border: '1px solid #bbf7d0', fontSize: '0.68rem', fontWeight: 700 }}>Success</span>
                      ) : (
                        <span title={row.error_detail ?? undefined} style={{ display: 'inline-block', padding: '0.1rem 0.5rem', borderRadius: '99px', background: '#fff5f5', color: R, border: '1px solid #f5c6c6', fontSize: '0.68rem', fontWeight: 700 }}>Failed</span>
                      )}
                    </td>
                    <td style={{ padding: '0.6rem 1rem', color: 'var(--adm-text-2)' }}>{row.triggered_by}</td>
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
