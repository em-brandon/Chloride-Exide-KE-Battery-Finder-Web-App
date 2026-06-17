import { useNavigate, useLocation, Link } from 'react-router-dom'
import { useState, useEffect } from 'react'
import type { ReactNode } from 'react'
import chlorideExideLogo from '@/assets/chlorideexidebrandlogo.webp'
import {
  Squares2X2Icon,
  BoltIcon,
  ClipboardDocumentListIcon,
  ShieldCheckIcon,
  ChartBarIcon,
  ChatBubbleLeftRightIcon,
  UserGroupIcon,
  CogIcon,
  ArrowRightStartOnRectangleIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  SunIcon,
  MoonIcon,
  ServerStackIcon,
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
  { to: '/admin/dashboard',     label: 'Dashboard',  Icon: Squares2X2Icon },
  { to: '/admin/batteries',     label: 'Batteries',  Icon: BoltIcon },
  { to: '/admin/audit',         label: 'Audit Log',  Icon: ClipboardDocumentListIcon },
  { to: '/admin/sessions',      label: 'Sessions',   Icon: ShieldCheckIcon },
  { to: '/admin/coverage',      label: 'Coverage',   Icon: ChartBarIcon },
  { to: '/admin/data-pipeline', label: 'Data Pipeline', Icon: ServerStackIcon },
  { to: '/admin/feedback',      label: 'Feedback',   Icon: ChatBubbleLeftRightIcon },
  { to: '/admin/test-sessions', label: 'Test Users', Icon: UserGroupIcon },
  { to: '/admin/settings',      label: 'Settings',   Icon: CogIcon },
]


// ── Layout ────────────────────────────────────────────────────────────────────
export default function AdminLayout({ children }: { children: ReactNode }) {
  const navigate     = useNavigate()
  const { pathname } = useLocation()

  // Read persisted state from localStorage so it survives route changes
  // (each page remounts AdminLayout, so component state alone won't persist).
  const [collapsed, setCollapsedState] = useState<boolean>(
    () => localStorage.getItem('sidebar_collapsed') === 'true'
  )
  const [dark, setDark] = useState<boolean>(
    () => localStorage.getItem('admin_dark') === '1'
  )

  function toggleDark() {
    setDark(prev => {
      const next = !prev
      localStorage.setItem('admin_dark', next ? '1' : '0')
      return next
    })
  }

  function setCollapsed(value: boolean | ((prev: boolean) => boolean)) {
    setCollapsedState(prev => {
      const next = typeof value === 'function' ? value(prev) : value
      localStorage.setItem('sidebar_collapsed', String(next))
      return next
    })
  }

  // When navigating to a page that needs more space (e.g. Feedback):
  // - If sidebar is expanded → collapse it
  // - If sidebar is already collapsed → leave it (no change)
  // This always fires regardless of the manual-toggle preference.
  useEffect(() => {
    if (AUTO_COLLAPSE_PATHS.includes(pathname)) {
      setCollapsed(true)
    }
  }, [pathname])

  const sidebarW = collapsed ? SIDEBAR_W_ICON : SIDEBAR_W

  const admVars = (dark ? {
    '--adm-card-bg':     '#161b22',
    '--adm-card-border': '#30363d',
    '--adm-card-shadow': '0 2px 12px rgba(0,0,0,0.4)',
    '--adm-header-bg':   '#161b22',
    '--adm-subtle-bg':   '#21262d',
    '--adm-faint-bg':    '#1e2329',
    '--adm-input-bg':    '#0d1117',
    '--adm-input-border':'#30363d',
    '--adm-text-1':      'rgba(229,231,235,0.9)',
    '--adm-text-2':      'rgba(156,163,175,0.7)',
    '--adm-text-3':      'rgba(156,163,175,0.8)',
    '--adm-row-hover':   '#21262d',
    '--adm-row-border':  '#21262d',
    '--adm-thead-bg':    '#1e2329',
    '--adm-sep':         '#30363d',
  } : {
    '--adm-card-bg':     '#ffffff',
    '--adm-card-border': '#e2e4e9',
    '--adm-card-shadow': '0 2px 12px rgba(0,0,0,0.07)',
    '--adm-header-bg':   '#ffffff',
    '--adm-subtle-bg':   '#f4f5f7',
    '--adm-faint-bg':    '#f9fafb',
    '--adm-input-bg':    '#ffffff',
    '--adm-input-border':'#d1d5db',
    '--adm-text-1':      'rgba(17,24,39,0.88)',
    '--adm-text-2':      'rgba(107,114,128,0.8)',
    '--adm-text-3':      'rgba(107,114,128,0.9)',
    '--adm-row-hover':   '#fff8f8',
    '--adm-row-border':  '#f0f1f4',
    '--adm-thead-bg':    '#f8f9fb',
    '--adm-sep':         '#e2e4e9',
  }) as React.CSSProperties

  async function handleLogout() {
    await adminLogout()
    navigate('/admin/login', { replace: true })
  }

  return (
    <div className={dark ? 'admin-dark' : ''} style={{ display: 'flex', minHeight: '100vh', fontFamily: "'Segoe UI', system-ui, sans-serif", ...admVars }}>

      {/* ── Sidebar ── */}
      <aside className="admin-sidebar" style={{
        width: sidebarW,
        minWidth: sidebarW,
        background: dark ? '#161b22' : '#fff',
        borderRight: dark ? '1px solid #30363d' : '1px solid #e2e4e9',
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
          padding: collapsed ? '0.9rem 0' : '0.9rem 1rem',
          borderBottom: dark ? '1px solid #30363d' : '1px solid #e2e4e9',
          display: 'flex',
          alignItems: 'center',
          justifyContent: collapsed ? 'center' : 'flex-start',
          gap: '0.65rem',
          minHeight: 56,
          overflow: 'hidden',
        }}>
          <img
            src={chlorideExideLogo}
            alt="Chloride Exide"
            style={{
              height: collapsed ? 28 : 36,
              width: 'auto',
              maxWidth: collapsed ? 36 : 120,
              objectFit: 'contain',
              display: 'block',
              flexShrink: 0,
              transition: 'height 0.2s',
            }}
          />
          {!collapsed && (
            <div style={{
              fontSize: '0.55rem',
              fontWeight: 700,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'rgba(107,114,128,0.85)',
              whiteSpace: 'nowrap',
            }}>
              Admin Panel
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
                  color: isActive ? R : dark ? 'rgba(229,231,235,0.65)' : 'rgba(17,24,39,0.65)',
                  background: isActive ? (dark ? '#2d1a1a' : '#fff5f5') : 'transparent',
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
                    e.currentTarget.style.background = dark ? '#21262d' : '#f4f5f7'
                    e.currentTarget.style.color = dark ? 'rgba(229,231,235,0.9)' : 'rgba(17,24,39,0.85)'
                  }
                }}
                onMouseLeave={e => {
                  if (!isActive) {
                    e.currentTarget.style.background = 'transparent'
                    e.currentTarget.style.color = dark ? 'rgba(229,231,235,0.65)' : 'rgba(17,24,39,0.65)'
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
        <div style={{ padding: collapsed ? '0.75rem 0' : '0.75rem', borderTop: dark ? '1px solid #30363d' : '1px solid #e2e4e9', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {/* Dark mode toggle */}
          <button
            onClick={toggleDark}
            title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
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
              color: dark ? 'rgba(229,231,235,0.6)' : 'rgba(107,114,128,0.8)',
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = dark ? '#21262d' : '#f4f5f7' }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
          >
            {dark
              ? <><SunIcon style={{ width: 16, height: 16, flexShrink: 0 }} />{!collapsed && <span>Light mode</span>}</>
              : <><MoonIcon style={{ width: 16, height: 16, flexShrink: 0 }} />{!collapsed && <span>Dark mode</span>}</>
            }
          </button>

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
              color: dark ? 'rgba(229,231,235,0.6)' : 'rgba(107,114,128,0.8)',
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = dark ? '#21262d' : '#f4f5f7' }}
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
      <div className="admin-main" style={{
        marginLeft: sidebarW,
        flex: 1,
        minHeight: '100vh',
        background: dark ? '#0f1117' : BG,
        display: 'flex',
        flexDirection: 'column',
        transition: 'margin-left 0.2s ease',
      }}>
        {children}
        <footer style={{
          textAlign: 'center',
          padding: '1.5rem',
          fontSize: '0.7rem',
          color: dark ? 'rgba(229,231,235,0.3)' : 'rgba(107,114,128,0.5)',
          marginTop: 'auto',
        }}>
          © 2026 Chloride Exide · Battery Finder Admin
        </footer>
      </div>

    </div>
  )
}
