import { useState, useCallback, useRef, useEffect } from 'react'
import chlorideExideLogo from '@/assets/chlorideexidebrandlogo.png'
import { Routes, Route, Navigate } from 'react-router-dom'
import { PageLoader } from '@/components/PageLoader'
import { VehicleFinderForm } from '@/components/VehicleFinderForm'
import { Moon, Sun, Settings } from 'lucide-react'
import { ProtectedRoute } from '@/components/admin/ProtectedRoute'
import AdminLogin        from '@/pages/admin/AdminLogin'
import AdminDashboard   from '@/pages/admin/AdminDashboard'
import AdminBatteries   from '@/pages/admin/AdminBatteries'
import AdminAuditLog    from '@/pages/admin/AdminAuditLog'
import AdminSessions    from '@/pages/admin/AdminSessions'
import AdminDataPipeline from '@/pages/admin/AdminDataPipeline'
import AdminFeedback      from '@/pages/admin/AdminFeedback'
import AdminTestSessions from '@/pages/admin/AdminTestSessions'
import TestUserLogin     from '@/pages/TestUserLogin'
import { TestUserProvider, useTestUser } from '@/lib/TestUserContext'

// ---------------------------------------------------------------------------
// Test-user gate — redirects to /login if not authenticated
// ---------------------------------------------------------------------------

function TestUserRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useTestUser()
  if (loading) return <PageLoader visible />
  if (!user)   return <Navigate to="/login" replace />
  return <>{children}</>
}

// ---------------------------------------------------------------------------
// Public finder page — extracted so App() stays clean
// ---------------------------------------------------------------------------

interface PublicAppProps {
  loaderVisible: boolean
  darkMode: boolean
  typeMode: boolean
  navEstConf: { pct: number; label: string; cls: string } | null
  confPopover: boolean
  popoverRef: React.RefObject<HTMLDivElement | null>
  onMakesLoaded: () => void
  onToggleDark: () => void
  onTypeModeChange: () => void
  onEstConfChange: (conf: { pct: number; label: string; cls: string } | null) => void
  onSetConfPopover: (v: (prev: boolean) => boolean) => void
}

function PublicApp({
  loaderVisible,
  darkMode,
  typeMode,
  navEstConf,
  confPopover,
  popoverRef,
  onMakesLoaded,
  onToggleDark,
  onTypeModeChange,
  onEstConfChange,
  onSetConfPopover,
}: PublicAppProps) {
  const { user, logout } = useTestUser()
  return (
    <>
      <PageLoader visible={loaderVisible} />

      <div className={`page-wrapper${darkMode ? ' page-dark' : ''}`}>
        {/* ── Nav bar ── */}
        <nav className="page-nav">
          {/* Left: Brand */}
          <div className="page-nav-brand">
            <img
              src={chlorideExideLogo}
              alt="Chloride Exide"
              style={{
                height: 38,
                width: 'auto',
                maxWidth: 130,
                objectFit: 'contain',
                display: 'block',
                flexShrink: 0,
              }}
            />
            <div className="page-brand-sub" style={{ alignSelf: 'center' }}>Battery Finder</div>
          </div>

          {/* Center: manual mode badges */}
          {typeMode && (
            <div className="nav-type-mode">
              <span className="badge nav-manual-badge"><Settings size={13} strokeWidth={1.75} style={{ marginRight: '5px', verticalAlign: 'middle' }} />Manual Mode Active</span>
              {navEstConf && navEstConf.pct > 0 && (
                <div className="nav-conf">
                  <div className="nav-conf-label-row" ref={popoverRef}>
                    <span className="nav-conf-label">Match Confidence</span>
                    <button
                      className="conf-info-btn"
                      onClick={() => onSetConfPopover(v => !v)}
                      aria-label="What is match confidence?"
                    >?</button>
                    {confPopover && (
                      <div className="conf-popover">
                        <strong>What is Match Confidence?</strong>
                        <p>This score estimates how accurately we can recommend a battery based on the details you've entered. The more information provided — model, year, fuel type and engine size — the higher and more reliable the score.</p>
                        <ul>
                          <li><span className="conf-dot high" />85%+ — All details provided</li>
                          <li><span className="conf-dot medium" />55–70% — Partial details</li>
                          <li><span className="conf-dot low" />40% — Make only</li>
                        </ul>
                      </div>
                    )}
                  </div>
                  <div className="bar-track nav-conf-bar">
                    <div className={navEstConf.cls} style={{ width: `${navEstConf.pct}%`, transition: 'width 0.5s ease' }} />
                  </div>
                  <span className="nav-conf-pct">{navEstConf.pct}% &mdash; {navEstConf.label}</span>
                </div>
              )}
            </div>
          )}

          {/* Right: Night mode toggle + Home + User */}
          <div className="nav-right-btns">
            {user && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ fontSize: '0.78rem', fontWeight: 600, color: '#374151' }}>
                  {user.username}
                </span>
                <button
                  onClick={() => logout()}
                  style={{
                    padding: '0.25rem 0.65rem',
                    borderRadius: '6px',
                    border: '1px solid #e2e4e9',
                    background: '#fff',
                    cursor: 'pointer',
                    fontSize: '0.75rem',
                    color: '#6b7280',
                    fontFamily: 'inherit',
                  }}
                  title="Sign out"
                >
                  Sign out
                </button>
              </div>
            )}
            <button
              className={`nav-dark-btn${darkMode ? ' active' : ''}`}
              onClick={onToggleDark}
              aria-label={darkMode ? 'Switch to day mode' : 'Switch to night mode'}
            >
              {darkMode
                ? <Sun size={16} strokeWidth={2} />
                : <Moon size={16} strokeWidth={2} />}
            </button>
            <a
              href="https://www.chlorideexide.com"
              target="_blank"
              rel="noopener noreferrer"
              className="nav-dark-btn"
              aria-label="Go to Chloride Exide website"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" style={{ width: '1rem', height: '1rem' }}>
                <path fillRule="evenodd" d="M9.293 2.293a1 1 0 0 1 1.414 0l7 7A1 1 0 0 1 17 11h-1v6a1 1 0 0 1-1 1h-2a1 1 0 0 1-1-1v-3a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v3a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-6H3a1 1 0 0 1-.707-1.707l7-7Z" clipRule="evenodd" />
              </svg>
            </a>
          </div>
        </nav>

        {/* ── Finder card (owns its own card layout) ── */}
        <VehicleFinderForm
          onMakesLoaded={onMakesLoaded}
          typeMode={typeMode}
          onTypeModeChange={onTypeModeChange}
          onEstConfChange={onEstConfChange}
          darkMode={darkMode}
        />

        {/* ── Footer — no separator ── */}
        <footer className="page-footer">
          &copy; 2026 Chloride Exide Battery Finder
        </footer>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Root app — owns shared state and router
// ---------------------------------------------------------------------------

function App() {
  const [loaderVisible, setLoaderVisible] = useState(true)
  const [darkMode, setDarkMode] = useState(false)
  const [typeMode, setTypeMode] = useState(false)
  const [navEstConf, setNavEstConf] = useState<{ pct: number; label: string; cls: string } | null>(null)
  const [confPopover, setConfPopover] = useState(false)
  const popoverRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!confPopover) return
    function handleClick(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setConfPopover(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [confPopover])

  const handleMakesLoaded = useCallback(() => { setLoaderVisible(false) }, [])
  const toggleDark        = useCallback(() => { setDarkMode(d => !d) }, [])
  const handleTypeModeChange = useCallback(() => { setTypeMode(t => !t); setNavEstConf(null) }, [])
  const handleEstConfChange  = useCallback((conf: { pct: number; label: string; cls: string } | null) => {
    setNavEstConf(conf)
  }, [])

  return (
    <TestUserProvider>
    <Routes>
      {/* ── Public finder ── */}
      <Route path="/" element={
        <TestUserRoute>
          <PublicApp
            loaderVisible={loaderVisible}
            darkMode={darkMode}
            typeMode={typeMode}
            navEstConf={navEstConf}
            confPopover={confPopover}
            popoverRef={popoverRef}
            onMakesLoaded={handleMakesLoaded}
            onToggleDark={toggleDark}
            onTypeModeChange={handleTypeModeChange}
            onEstConfChange={handleEstConfChange}
            onSetConfPopover={setConfPopover}
          />
        </TestUserRoute>
      } />

      {/* ── Admin ── */}
      <Route path="/admin/login"     element={<AdminLogin />} />
      <Route path="/admin/dashboard" element={<ProtectedRoute><AdminDashboard /></ProtectedRoute>} />
      <Route path="/admin/batteries" element={<ProtectedRoute><AdminBatteries /></ProtectedRoute>} />
      <Route path="/admin/audit"     element={<ProtectedRoute><AdminAuditLog  /></ProtectedRoute>} />
      <Route path="/admin/sessions"  element={<ProtectedRoute><AdminSessions  /></ProtectedRoute>} />
      <Route path="/admin/pipeline"  element={<ProtectedRoute><AdminDataPipeline /></ProtectedRoute>} />
      <Route path="/admin/feedback"      element={<ProtectedRoute><AdminFeedback      /></ProtectedRoute>} />
      <Route path="/admin/test-sessions" element={<ProtectedRoute><AdminTestSessions /></ProtectedRoute>} />
      {/* ── Test user login ── */}
      <Route path="/login" element={<TestUserLogin />} />
    </Routes>
    </TestUserProvider>
  )
}

export default App

