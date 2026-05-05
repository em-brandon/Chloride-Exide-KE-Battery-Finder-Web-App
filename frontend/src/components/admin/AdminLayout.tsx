import { useNavigate, useLocation, Link } from 'react-router-dom'
import type { ReactNode } from 'react'
import {
  Squares2X2Icon,
  BoltIcon,
  ClipboardDocumentListIcon,
  ShieldCheckIcon,
  FunnelIcon,
  ArrowRightStartOnRectangleIcon,
} from '@heroicons/react/20/solid'
import { adminLogout } from '@/lib/adminApi'

// ── Design tokens ─────────────────────────────────────────────────────────────
const R  = '#CC0000'
const BG = 'linear-gradient(160deg, #f4f5f7 0%, #eef0f4 100%)'
const SIDEBAR_W = 220

const NAV_ITEMS = [
  { to: '/admin/dashboard', label: 'Dashboard',     Icon: Squares2X2Icon },
  { to: '/admin/batteries', label: 'Batteries',     Icon: BoltIcon },
  { to: '/admin/audit',     label: 'Audit Log',     Icon: ClipboardDocumentListIcon },
  { to: '/admin/sessions',  label: 'Sessions',      Icon: ShieldCheckIcon },
  { to: '/admin/pipeline',  label: 'Data Pipeline', Icon: FunnelIcon },
]

// ── Brand battery SVG ─────────────────────────────────────────────────────────
function BatteryLogo() {
  return (
    <svg width="30" height="30" viewBox="0 0 56 56" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="4" y="18" width="48" height="28" rx="3" fill={R}/>
      <rect x="5" y="19" width="46" height="26" rx="2" fill="#f3f3f3" stroke={R} strokeWidth="1"/>
      <rect x="11" y="12" width="8" height="7" rx="1.5" fill={R}/>
      <rect x="37" y="12" width="8" height="7" rx="1.5" fill="#888"/>
      <text x="15" y="18.5" textAnchor="middle" fontSize="6" fontWeight="bold" fill="#fff">+</text>
      <text x="41" y="18.5" textAnchor="middle" fontSize="7" fontWeight="bold" fill="#fff">−</text>
      <line x1="18" y1="21" x2="18" y2="43" stroke={R} strokeWidth="1.2" opacity="0.5"/>
      <line x1="28" y1="21" x2="28" y2="43" stroke={R} strokeWidth="1.2" opacity="0.5"/>
      <line x1="38" y1="21" x2="38" y2="43" stroke={R} strokeWidth="1.2" opacity="0.5"/>
    </svg>
  )
}

// ── Layout ────────────────────────────────────────────────────────────────────
export default function AdminLayout({ children }: { children: ReactNode }) {
  const navigate    = useNavigate()
  const { pathname } = useLocation()

  async function handleLogout() {
    await adminLogout()
    navigate('/admin/login', { replace: true })
  }

  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: "'Segoe UI', system-ui, sans-serif" }}>

      {/* ── Sidebar ── */}
      <aside style={{
        width: SIDEBAR_W,
        minWidth: SIDEBAR_W,
        background: '#fff',
        borderRight: '1px solid #e2e4e9',
        boxShadow: '2px 0 12px rgba(0,0,0,0.05)',
        display: 'flex',
        flexDirection: 'column',
        position: 'fixed',
        top: 0,
        left: 0,
        bottom: 0,
        zIndex: 50,
      }}>

        {/* Brand */}
        <div style={{
          padding: '1.1rem 1rem',
          borderBottom: '1px solid #e2e4e9',
          display: 'flex',
          alignItems: 'center',
          gap: '0.65rem',
        }}>
          <BatteryLogo />
          <div>
            <div style={{
              fontSize: '0.88rem',
              fontWeight: 800,
              letterSpacing: '0.02em',
              color: 'rgba(17,24,39,0.88)',
              lineHeight: 1,
            }}>
              CHLORIDE <span style={{ color: R }}>EXIDE</span>
            </div>
            <div style={{
              fontSize: '0.55rem',
              fontWeight: 600,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'rgba(107,114,128,0.9)',
              marginTop: '0.18rem',
            }}>
              Admin Panel
            </div>
          </div>
        </div>

        {/* Nav links */}
        <nav style={{
          flex: 1,
          padding: '0.85rem 0.75rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.2rem',
          overflowY: 'auto',
        }}>
          {NAV_ITEMS.map(({ to, label, Icon }) => {
            const isActive = pathname === to
            return (
              <Link
                key={to}
                to={to}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.65rem',
                  padding: '0.62rem 0.85rem',
                  borderRadius: '10px',
                  fontSize: '0.85rem',
                  fontWeight: isActive ? 700 : 500,
                  color: isActive ? R : 'rgba(17,24,39,0.65)',
                  background: isActive ? '#fff5f5' : 'transparent',
                  textDecoration: 'none',
                  borderLeft: `3px solid ${isActive ? R : 'transparent'}`,
                  transition: 'all 0.15s',
                }}
                onMouseEnter={e => {
                  if (!isActive) {
                    e.currentTarget.style.background = '#f4f5f7'
                    e.currentTarget.style.color = 'rgba(17,24,39,0.85)'
                  }
                }}
                onMouseLeave={e => {
                  if (!isActive) {
                    e.currentTarget.style.background = 'transparent'
                    e.currentTarget.style.color = 'rgba(17,24,39,0.65)'
                  }
                }}
              >
                <Icon style={{ width: 17, height: 17, flexShrink: 0 }} />
                {label}
              </Link>
            )
          })}
        </nav>

        {/* Sign out */}
        <div style={{ padding: '0.75rem', borderTop: '1px solid #e2e4e9' }}>
          <button
            onClick={handleLogout}
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              gap: '0.65rem',
              padding: '0.62rem 0.85rem',
              borderRadius: '10px',
              fontSize: '0.85rem',
              fontWeight: 600,
              color: R,
              background: '#fff5f5',
              border: '1px solid #fecaca',
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = R; e.currentTarget.style.color = '#fff' }}
            onMouseLeave={e => { e.currentTarget.style.background = '#fff5f5'; e.currentTarget.style.color = R }}
          >
            <ArrowRightStartOnRectangleIcon style={{ width: 17, height: 17, flexShrink: 0 }} />
            Sign Out
          </button>
        </div>
      </aside>

      {/* ── Content area ── */}
      <div style={{
        marginLeft: SIDEBAR_W,
        flex: 1,
        minHeight: '100vh',
        background: BG,
        display: 'flex',
        flexDirection: 'column',
      }}>
        {children}
        <footer style={{
          textAlign: 'center',
          padding: '1.5rem',
          fontSize: '0.7rem',
          color: 'rgba(107,114,128,0.5)',
          marginTop: 'auto',
        }}>
          © 2026 Chloride Exide · Battery Finder Admin
        </footer>
      </div>

    </div>
  )
}
