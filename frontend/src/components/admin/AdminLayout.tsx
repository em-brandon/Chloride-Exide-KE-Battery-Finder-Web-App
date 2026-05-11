import { useNavigate, useLocation, Link } from 'react-router-dom'
import { useState, useEffect } from 'react'
import type { ReactNode } from 'react'
import {
  Squares2X2Icon,
  BoltIcon,
  ClipboardDocumentListIcon,
  ShieldCheckIcon,
  FunnelIcon,
  ChatBubbleLeftRightIcon,
  UserGroupIcon,
  ArrowRightStartOnRectangleIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
} from '@heroicons/react/20/solid'
import { adminLogout } from '@/lib/adminApi'

// ── Design tokens ─────────────────────────────────────────────────────────────
const R  = '#CC0000'
const BG = 'linear-gradient(160deg, #f4f5f7 0%, #eef0f4 100%)'
const SIDEBAR_W      = 180
const SIDEBAR_W_ICON = 52

// Pages that auto-collapse the sidebar for more content space
const AUTO_COLLAPSE_PATHS = ['/admin/feedback']

const NAV_ITEMS = [
  { to: '/admin/dashboard',     label: 'Dashboard',     Icon: Squares2X2Icon },
  { to: '/admin/batteries',     label: 'Batteries',     Icon: BoltIcon },
  { to: '/admin/audit',         label: 'Audit Log',     Icon: ClipboardDocumentListIcon },
  { to: '/admin/sessions',      label: 'Sessions',      Icon: ShieldCheckIcon },
  { to: '/admin/pipeline',      label: 'Data Pipeline', Icon: FunnelIcon },
  { to: '/admin/feedback',      label: 'Feedback',      Icon: ChatBubbleLeftRightIcon },
  { to: '/admin/test-sessions', label: 'Test Users',    Icon: UserGroupIcon },
]

// ── Brand battery SVG ─────────────────────────────────────────────────────────
function BatteryLogo() {
  return (
    <svg width="26" height="26" viewBox="0 0 24 24" fill={R} xmlns="http://www.w3.org/2000/svg">
      <path fillRule="evenodd" d="M14.615 1.595a.75.75 0 0 1 .359.852L12.982 9.75h7.268a.75.75 0 0 1 .548 1.262l-10.5 11.25a.75.75 0 0 1-1.272-.71l1.992-7.302H3.75a.75.75 0 0 1-.548-1.262l10.5-11.25a.75.75 0 0 1 .913-.143Z" clipRule="evenodd" />
    </svg>
  )
}

// ── Layout ────────────────────────────────────────────────────────────────────
export default function AdminLayout({ children }: { children: ReactNode }) {
  const navigate     = useNavigate()
  const { pathname } = useLocation()

  // Read persisted state from localStorage so it survives route changes
  // (each page remounts AdminLayout, so component state alone won't persist).
  const [collapsed, setCollapsedState] = useState<boolean>(
    () => localStorage.getItem('sidebar_collapsed') === 'true'
  )

  function setCollapsed(value: boolean | ((prev: boolean) => boolean)) {
    setCollapsedState(prev => {
      const next = typeof value === 'function' ? value(prev) : value
      localStorage.setItem('sidebar_collapsed', String(next))
      return next
    })
  }

  // Auto-collapse on pages that need more space, unless the user has
  // already expressed a preference by clicking the toggle button.
  useEffect(() => {
    const manuallyToggled = localStorage.getItem('sidebar_manually_toggled') === 'true'
    if (!manuallyToggled && AUTO_COLLAPSE_PATHS.includes(pathname)) {
      setCollapsed(true)
    }
  }, [pathname])

  const sidebarW = collapsed ? SIDEBAR_W_ICON : SIDEBAR_W

  async function handleLogout() {
    await adminLogout()
    navigate('/admin/login', { replace: true })
  }

  return (
    <div style={{ display: 'flex', minHeight: '100vh', fontFamily: "'Segoe UI', system-ui, sans-serif" }}>

      {/* ── Sidebar ── */}
      <aside style={{
        width: sidebarW,
        minWidth: sidebarW,
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
        transition: 'width 0.2s ease',
        overflow: 'hidden',
      }}>

        {/* Brand */}
        <div style={{
          padding: collapsed ? '1.1rem 0' : '1.1rem 1rem',
          borderBottom: '1px solid #e2e4e9',
          display: 'flex',
          alignItems: 'center',
          justifyContent: collapsed ? 'center' : 'flex-start',
          gap: '0.65rem',
          minHeight: 56,
          overflow: 'hidden',
        }}>
          <BatteryLogo />
          {!collapsed && (
            <div style={{ whiteSpace: 'nowrap' }}>
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
          )}
        </div>

        {/* Nav links */}
        <nav style={{
          flex: 1,
          padding: collapsed ? '0.85rem 0' : '0.85rem 0.75rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.2rem',
          overflowY: 'auto',
          overflowX: 'hidden',
        }}>
          {NAV_ITEMS.map(({ to, label, Icon }) => {
            const isActive = pathname === to
            return (
              <Link
                key={to}
                to={to}
                title={collapsed ? label : undefined}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: collapsed ? 'center' : 'flex-start',
                  gap: collapsed ? 0 : '0.65rem',
                  padding: collapsed ? '0.62rem 0' : '0.62rem 0.85rem',
                  borderRadius: '10px',
                  fontSize: '0.85rem',
                  fontWeight: isActive ? 700 : 500,
                  color: isActive ? R : 'rgba(17,24,39,0.65)',
                  background: isActive ? '#fff5f5' : 'transparent',
                  textDecoration: 'none',
                  borderLeft: collapsed ? 'none' : `3px solid ${isActive ? R : 'transparent'}`,
                  borderRight: collapsed ? `3px solid ${isActive ? R : 'transparent'}` : 'none',
                  transition: 'all 0.15s',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  margin: collapsed ? '0 4px' : undefined,
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
                <Icon style={{ width: 18, height: 18, flexShrink: 0 }} />
                {!collapsed && <span>{label}</span>}
              </Link>
            )
          })}
        </nav>

        {/* Sign out + toggle */}
        <div style={{ padding: collapsed ? '0.75rem 0' : '0.75rem', borderTop: '1px solid #e2e4e9', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {/* Collapse toggle */}
          <button
            onClick={() => {
              localStorage.setItem('sidebar_manually_toggled', 'true')
              setCollapsed(c => !c)
            }}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: collapsed ? 'center' : 'flex-start',
              gap: collapsed ? 0 : '0.65rem',
              padding: collapsed ? '0.5rem 0' : '0.5rem 0.85rem',
              borderRadius: '10px',
              fontSize: '0.78rem',
              fontWeight: 500,
              color: 'rgba(107,114,128,0.8)',
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = '#f4f5f7' }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
          >
            {collapsed
              ? <ChevronRightIcon style={{ width: 16, height: 16 }} />
              : <><ChevronLeftIcon style={{ width: 16, height: 16, flexShrink: 0 }} /><span>Collapse</span></>
            }
          </button>

          {/* Sign out */}
          <button
            onClick={handleLogout}
            title={collapsed ? 'Sign Out' : undefined}
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: collapsed ? 'center' : 'flex-start',
              gap: collapsed ? 0 : '0.65rem',
              padding: collapsed ? '0.62rem 0' : '0.62rem 0.85rem',
              borderRadius: '10px',
              fontSize: '0.85rem',
              fontWeight: 600,
              color: R,
              background: '#fff5f5',
              border: '1px solid #fecaca',
              cursor: 'pointer',
              transition: 'all 0.15s',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = R; e.currentTarget.style.color = '#fff' }}
            onMouseLeave={e => { e.currentTarget.style.background = '#fff5f5'; e.currentTarget.style.color = R }}
          >
            <ArrowRightStartOnRectangleIcon style={{ width: 17, height: 17, flexShrink: 0 }} />
            {!collapsed && 'Sign Out'}
          </button>
        </div>
      </aside>

      {/* ── Content area ── */}
      <div style={{
        marginLeft: sidebarW,
        flex: 1,
        minHeight: '100vh',
        background: BG,
        display: 'flex',
        flexDirection: 'column',
        transition: 'margin-left 0.2s ease',
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
