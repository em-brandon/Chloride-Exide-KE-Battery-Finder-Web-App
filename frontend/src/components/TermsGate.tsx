import { useState } from 'react'
import chlorideExideLogo from '@/assets/chlorideexidebrandlogo.webp'
import { FaqModal } from '@/components/FaqModal'
import { ExclamationTriangleIcon } from '@heroicons/react/24/solid'

interface TermsGateProps {
  onAccept: () => void
}

export function TermsGate({ onAccept }: TermsGateProps) {
  const [checked, setChecked] = useState(false)
  const [faqOpen, setFaqOpen] = useState(false)

  return (
    <>
      <div className="tg-screen">
        <div className="tg-card">
          {/* Brand */}
          <div className="tg-brand">
            <img
              src={chlorideExideLogo}
              alt="Chloride Exide"
              className="tg-logo"
            />
            <span className="tg-brand-sub">Battery Finder</span>
          </div>

          <h1 className="tg-heading">
            <ExclamationTriangleIcon className="tg-heading-icon" />
            Before You Continue
          </h1>
          <p className="tg-intro">
            Please read and acknowledge the following disclaimer before using
            the Chloride Exide Battery Finder.
          </p>

          {/* Summary disclaimer */}
          <div className="tg-disclaimer-box">
            <ul className="tg-disclaimer-list">
              <li>
                Recommendations are based on vehicle specification data and
                real-world fitment records. They are a <strong>starting guide only</strong>,
                not a guaranteed fitment.
              </li>
              <li>
                Results depend on the accuracy of the vehicle details you
                provide. Always verify with a qualified technician or
                Chloride Exide dealer before purchase.
              </li>
              <li>
                Always confirm <strong>physical dimensions</strong>,{' '}
                <strong>terminal polarity</strong>, and{' '}
                <strong>terminal position</strong> before installing any battery.
              </li>
              <li style={{ color: '#CC0000', fontWeight: 700 }}>
                Chloride Exide Kenya accepts no liability for adverse outcomes
                arising from reliance on these recommendations without
                professional verification.
              </li>
            </ul>
            <button
              className="tg-read-more"
              onClick={() => setFaqOpen(true)}
            >
              Read full Disclaimer ↗
            </button>
          </div>

          {/* Checkbox */}
          <label className="tg-check-row">
            <input
              type="checkbox"
              className="tg-checkbox"
              checked={checked}
              onChange={e => setChecked(e.target.checked)}
            />
            <span className="tg-check-label">
              I have read and understood the above. I agree that recommendations
              are a starting guide and will verify battery specifications with a
              qualified dealer before purchase.
            </span>
          </label>

          {/* CTA */}
          <button
            className={`tg-continue${checked ? ' tg-continue--ready' : ''}`}
            disabled={!checked}
            onClick={onAccept}
          >
            Continue to Battery Finder
          </button>
        </div>
      </div>

      <FaqModal open={faqOpen} onClose={() => setFaqOpen(false)} initialTab="disclaimer" singleTab />
    </>
  )
}
