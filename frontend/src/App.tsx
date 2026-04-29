import { useState, useCallback } from 'react'
import { PageLoader } from '@/components/PageLoader'
import { VehicleFinderForm } from '@/components/VehicleFinderForm'
import { Moon, Sun } from 'lucide-react'

function App() {
  const [loaderVisible, setLoaderVisible] = useState(true)
  const [darkMode, setDarkMode] = useState(false)

  const handleMakesLoaded = useCallback(() => {
    setLoaderVisible(false)
  }, [])

  const toggleDark = useCallback(() => {
    setDarkMode(d => !d)
  }, [])

  return (
    <>
      <PageLoader visible={loaderVisible} />

      <div className={`page-wrapper${darkMode ? ' page-dark' : ''}`}>
        {/* ── Nav bar ── */}
        <nav className="page-nav">
          {/* Left: Brand */}
          <div className="page-nav-brand">
            <svg width="40" height="40" viewBox="0 0 56 56" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <rect x="4" y="18" width="48" height="28" rx="3" fill="#CC0000"/>
              <rect x="5" y="19" width="46" height="26" rx="2" fill="#f3f3f3" stroke="#CC0000" strokeWidth="1"/>
              <rect x="11" y="12" width="8" height="7" rx="1.5" fill="#CC0000"/>
              <rect x="37" y="12" width="8" height="7" rx="1.5" fill="#888888"/>
              <text x="15" y="18.5" textAnchor="middle" fontSize="6" fontWeight="bold" fill="#fff">+</text>
              <text x="41" y="18.5" textAnchor="middle" fontSize="7" fontWeight="bold" fill="#fff">−</text>
              <line x1="18" y1="21" x2="18" y2="43" stroke="#CC0000" strokeWidth="1.2" opacity="0.5"/>
              <line x1="28" y1="21" x2="28" y2="43" stroke="#CC0000" strokeWidth="1.2" opacity="0.5"/>
              <line x1="38" y1="21" x2="38" y2="43" stroke="#CC0000" strokeWidth="1.2" opacity="0.5"/>
              <circle cx="13" cy="33" r="1.8" fill="#CC0000" opacity="0.4"/>
              <circle cx="23" cy="33" r="1.8" fill="#CC0000" opacity="0.4"/>
              <circle cx="33" cy="33" r="1.8" fill="#CC0000" opacity="0.4"/>
              <circle cx="43" cy="33" r="1.8" fill="#CC0000" opacity="0.4"/>
            </svg>
            <div>
              <div className="page-brand-name">
                CHLORIDE <span style={{ color: 'var(--red)' }}>EXIDE</span>
              </div>
              <div className="page-brand-sub">Battery Finder</div>
            </div>
          </div>

          {/* Right: Night mode toggle */}
          <button
            className={`nav-dark-btn${darkMode ? ' active' : ''}`}
            onClick={toggleDark}
            aria-label={darkMode ? 'Switch to day mode' : 'Switch to night mode'}
          >
            {darkMode
              ? <Sun size={16} strokeWidth={2} />
              : <Moon size={16} strokeWidth={2} />}
          </button>
        </nav>

        {/* ── Tagline ── */}
        <p className="page-tagline">
          Enter your vehicle details to get the right battery recommendation
        </p>

        {/* ── Finder card (owns its own card layout) ── */}
        <VehicleFinderForm
          onMakesLoaded={handleMakesLoaded}
        />

        {/* ── Footer — no separator ── */}
        <footer className="page-footer">
          Chloride Exide Battery Finder &mdash; Data sourced from CRSP dataset
        </footer>
      </div>
    </>
  )
}

export default App

