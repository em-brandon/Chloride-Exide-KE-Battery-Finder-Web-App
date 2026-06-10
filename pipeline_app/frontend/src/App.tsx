import { useState, useEffect } from 'react'
import { api } from './lib/api'
import { LoginPage } from './pages/LoginPage'
import { WebValidatePage } from './pages/WebValidatePage'
import { CrspPage } from './pages/CrspPage'
import { MasterRecordsPage } from './pages/MasterRecordsPage'
import { ArrowRightOnRectangleIcon, GlobeAltIcon, TableCellsIcon, CircleStackIcon } from '@heroicons/react/20/solid'
import chlorideExideBrandLogo from '@/assets/chlorideexidebrandlogo.png'

const R = '#CC0000'

export default function App() {
  const [username, setUsername] = useState<string | null>(null)
  const [checking, setChecking]  = useState(true)
  const [tab, setTab] = useState<'web-validate' | 'crsp' | 'master-records'>('web-validate')

  useEffect(() => {
    api.me().then(r => setUsername(r.username)).catch(() => {}).finally(() => setChecking(false))
  }, [])

  if (checking) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: '#6b7280' }}>
      Loading…
    </div>
  )

  if (!username) return (
    <LoginPage onLogin={(u) => setUsername(u)} />
  )

  return (
    <div style={{ minHeight: '100vh', background: '#f4f5f7', fontFamily: "'Segoe UI', system-ui, sans-serif" }}>
      {/* Header */}
      <header style={{
        background: '#fff', borderBottom: '2px solid #e2e4e9',
        padding: '0 1.5rem', height: 60,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        position: 'sticky', top: 0, zIndex: 40,
        boxShadow: '0 2px 12px rgba(0,0,0,0.08)',
      }}>
        {/* Left: Brand + tabs */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
          {/* Logo */}
          <div style={{ paddingRight: '1.25rem', borderRight: '1px solid #e2e4e9', display: 'flex', alignItems: 'center' }}>
            <img src={chlorideExideBrandLogo} alt="Chloride Exide"
              style={{ height: 44, width: 'auto', objectFit: 'contain' }} />
          </div>

          {/* Tabs — segmented control */}
          <div style={{ display: 'flex', background: '#f0f1f4', borderRadius: 10, padding: 3, gap: 2 }}>
            {(['web-validate', 'crsp', 'master-records'] as const).map(t => (
              <button key={t} onClick={() => setTab(t)} style={{
                display: 'flex', alignItems: 'center', gap: '0.35rem',
                background: tab === t ? '#fff' : 'transparent',
                border: 'none', cursor: 'pointer',
                padding: '0.35rem 0.85rem',
                borderRadius: 8,
                fontSize: '0.82rem', fontWeight: tab === t ? 700 : 500,
                color: tab === t ? R : '#6b7280',
                boxShadow: tab === t ? '0 1px 4px rgba(0,0,0,0.10)' : 'none',
                transition: 'all 0.15s',
              }}>
                {t === 'web-validate'
                  ? <GlobeAltIcon style={{ width: 13, height: 13 }} />
                  : t === 'crsp'
                  ? <TableCellsIcon style={{ width: 13, height: 13 }} />
                  : <CircleStackIcon style={{ width: 13, height: 13 }} />
                }
                {t === 'web-validate' ? 'Web Validate' : t === 'crsp' ? 'CRSP Dataset' : 'Master Records'}
              </button>
            ))}
          </div>
        </div>

        {/* Right: user + sign out */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <span style={{ fontSize: '0.78rem', fontWeight: 600, color: '#374151' }}>{username}</span>
          <button onClick={async () => {
            await api.logout().catch(() => {})
            setUsername(null)
          }} style={{
            display: 'flex', alignItems: 'center', gap: '0.35rem',
            fontSize: '0.75rem', fontWeight: 600, color: R,
            background: '#fff5f5', border: '1px solid #fecaca',
            borderRadius: 8, padding: '0.3rem 0.75rem', cursor: 'pointer',
          }}>
            <ArrowRightOnRectangleIcon style={{ width: 15, height: 15 }} />
            Sign out
          </button>
        </div>
      </header>

      {/* Content */}
      <main style={{ padding: '1.5rem', maxWidth: 1200, margin: '0 auto' }}>
        {tab === 'web-validate'
          ? <WebValidatePage />
          : tab === 'crsp'
          ? <CrspPage />
          : <MasterRecordsPage />
        }
      </main>
    </div>
  )
}
