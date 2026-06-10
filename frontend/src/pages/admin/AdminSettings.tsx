import { useState, useEffect } from 'react'
import AdminLayout from '@/components/admin/AdminLayout'
import { getMaintenanceMode, setMaintenanceMode } from '@/lib/adminApi'
import { WrenchScrewdriverIcon, ExclamationTriangleIcon, ArrowTopRightOnSquareIcon } from '@heroicons/react/24/outline'

export default function AdminSettings() {
  const [enabled, setEnabled]   = useState(false)
  const [loading, setLoading]   = useState(true)
  const [saving,  setSaving]    = useState(false)
  const [error,   setError]     = useState<string | null>(null)

  useEffect(() => {
    getMaintenanceMode()
      .then(r => setEnabled(r.enabled))
      .catch(() => setError('Failed to load maintenance mode status.'))
      .finally(() => setLoading(false))
  }, [])

  async function handleToggle() {
    setSaving(true)
    setError(null)
    try {
      const result = await setMaintenanceMode(!enabled)
      setEnabled(result.enabled)
    } catch {
      setError('Failed to update maintenance mode.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <AdminLayout>
      <div style={{ padding: '2rem', maxWidth: 640 }}>

        {/* Page header */}
        <div style={{ marginBottom: '1.75rem' }}>
          <h1 style={{
            fontSize: '1.25rem', fontWeight: 800,
            color: 'var(--adm-text-1)', margin: 0, display: 'flex',
            alignItems: 'center', gap: '0.5rem',
          }}>
            <WrenchScrewdriverIcon style={{ width: 22, height: 22 }} />
            Settings
          </h1>
          <p style={{ margin: '0.35rem 0 0', fontSize: '0.83rem', color: 'var(--adm-text-2)' }}>
            Runtime configuration — changes take effect immediately, no restart needed.
          </p>
        </div>

        {/* Error */}
        {error && (
          <div style={{
            background: '#fef2f2', border: '1px solid #fecaca',
            borderRadius: 8, padding: '0.65rem 0.9rem',
            fontSize: '0.8rem', color: '#b91c1c', marginBottom: '1rem',
          }}>
            {error}
          </div>
        )}

        {/* Maintenance mode card */}
        <div style={{
          background: 'var(--adm-card-bg)',
          border: `1px solid ${enabled ? '#fca5a5' : 'var(--adm-card-border)'}`,
          borderRadius: 12,
          boxShadow: 'var(--adm-card-shadow)',
          overflow: 'hidden',
          transition: 'border-color 0.2s',
        }}>

          {/* Active banner */}
          {enabled && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: '0.5rem',
              background: '#CC0000', color: '#fff',
              padding: '0.6rem 1.1rem',
              fontSize: '0.78rem', fontWeight: 600,
            }}>
              <ExclamationTriangleIcon style={{ width: 15, height: 15, flexShrink: 0 }} />
              The public site is currently showing the maintenance page. Visitors cannot access the app.
            </div>
          )}

          <div style={{ padding: '1.25rem 1.4rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem' }}>

            {/* Label */}
            <div>
              <div style={{ fontWeight: 700, fontSize: '0.93rem', color: 'var(--adm-text-1)' }}>
                Maintenance Mode
              </div>
              <div style={{ fontSize: '0.78rem', color: 'var(--adm-text-2)', marginTop: '0.2rem', maxWidth: 380 }}>
                When ON, all public routes serve the maintenance page. Admin routes remain accessible.
              </div>
            </div>

            {/* Toggle */}
            <button
              onClick={handleToggle}
              disabled={loading || saving}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.45rem',
                padding: '0.45rem 1.1rem',
                borderRadius: 8,
                fontSize: '0.82rem', fontWeight: 700,
                border: 'none', cursor: loading || saving ? 'not-allowed' : 'pointer',
                background: enabled ? '#CC0000' : '#16a34a',
                color: '#fff',
                opacity: loading || saving ? 0.65 : 1,
                transition: 'background 0.2s, opacity 0.15s',
                flexShrink: 0, whiteSpace: 'nowrap',
              }}
              onMouseEnter={e => {
                if (!loading && !saving) {
                  e.currentTarget.style.background = enabled ? '#990000' : '#15803d'
                }
              }}
              onMouseLeave={e => {
                if (!loading && !saving) {
                  e.currentTarget.style.background = enabled ? '#CC0000' : '#16a34a'
                }
              }}
            >
              {saving ? 'Saving…' : loading ? 'Loading…' : enabled ? 'Turn OFF' : 'Turn ON'}
            </button>
          </div>

          {/* Status footer */}
          <div style={{
            borderTop: '1px solid var(--adm-sep)',
            padding: '0.55rem 1.4rem',
            fontSize: '0.73rem',
            color: 'var(--adm-text-2)',
            background: 'var(--adm-faint-bg)',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <span>
              Status:&nbsp;
              <span style={{ fontWeight: 700, color: enabled ? '#CC0000' : '#16a34a' }}>
                {loading ? '—' : enabled ? 'ON' : 'OFF'}
              </span>
            </span>
            <a
              href="/static/maintenance.html"
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.25rem',
                fontSize: '0.72rem', fontWeight: 600,
                color: 'var(--adm-text-2)', textDecoration: 'none',
              }}
              onMouseEnter={e => { (e.currentTarget as HTMLAnchorElement).style.color = '#CC0000' }}
              onMouseLeave={e => { (e.currentTarget as HTMLAnchorElement).style.color = 'var(--adm-text-2)' }}
            >
              <ArrowTopRightOnSquareIcon style={{ width: 12, height: 12 }} />
              Preview page
            </a>
          </div>
        </div>

      </div>
    </AdminLayout>
  )
}
