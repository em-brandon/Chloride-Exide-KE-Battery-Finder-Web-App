import { useEffect, useRef } from 'react'
import { XMarkIcon } from '@heroicons/react/24/outline'

interface PrivacyModalProps {
  open: boolean
  onClose: () => void
}

export function PrivacyModal({ open, onClose }: PrivacyModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="faq-overlay"
      ref={overlayRef}
      onMouseDown={e => { if (e.target === overlayRef.current) onClose() }}
      role="dialog"
      aria-modal="true"
      aria-label="Privacy Policy"
    >
      <div className="faq-modal">
        {/* Header */}
        <div className="faq-modal__header">
          <span className="faq-modal__title">Privacy Policy</span>
          <button className="faq-modal__close" onClick={onClose} aria-label="Close">
            <XMarkIcon style={{ width: 18, height: 18 }} />
          </button>
        </div>

        {/* Body */}
        <div className="faq-modal__body">
          <div className="faq-prose">

            <p className="copyright-year">Chloride Exide (Kenya) Limited — Battery Finder Privacy Policy</p>
            <p style={{ fontSize: '0.8rem', marginTop: '-0.5rem' }}>Effective: May 2026</p>

            <p><strong>What This Tool Collects</strong></p>
            <p>
              The Battery Finder is designed to collect as little personal data as possible. When you use the tool, the following information may be recorded:
            </p>
            <ul className="faq-inner-list">
              <li><strong>Vehicle search queries</strong> — the make, model, year, engine size, and fuel type you enter. This data is used solely to generate your battery recommendation and to improve the accuracy of our vehicle database over time.</li>
              <li><strong>IP address</strong> — your network IP address is logged automatically with each request for rate limiting and abuse prevention purposes. It is not used to build a profile of you.</li>
              <li><strong>Optional feedback</strong> — if you submit a satisfaction rating or accuracy score after receiving a recommendation, that rating is stored alongside the anonymised match details (vehicle category, battery code, confidence level). No name, email, or other identifying information is requested or stored with feedback.</li>
            </ul>

            <p><strong>Session Data</strong></p>
            <ul className="faq-inner-list">
              <li>If you have been granted a test-user account, a session token is stored in your browser's local storage with a 24-hour expiry. This token identifies your session for support and testing purposes only.</li>
              <li>Your acknowledgement of this disclaimer is stored in your browser's session storage and is cleared automatically when you close your browser tab.</li>
              <li>No tracking cookies, advertising cookies, or third-party analytics scripts are used on this application.</li>
            </ul>

            <p><strong>How We Use Your Data</strong></p>
            <ul className="faq-inner-list">
              <li>To return an accurate battery recommendation for your vehicle.</li>
              <li>To prevent automated abuse and enforce fair-use rate limits.</li>
              <li>To identify gaps in our vehicle database and prioritise updates.</li>
              <li>Aggregated, anonymised usage patterns may be reviewed internally to improve the tool — no individual usage history is shared outside Chloride Exide Kenya.</li>
            </ul>

            <p><strong>Data Retention</strong></p>
            <ul className="faq-inner-list">
              <li>Raw IP logs are retained for a limited period for abuse investigation purposes and are not linked to your search queries beyond the immediate request.</li>
              <li>Anonymised feedback and usage statistics are retained indefinitely for product improvement.</li>
              <li>No personal data is sold, rented, or disclosed to third parties for marketing purposes.</li>
            </ul>

            <p><strong>Third Parties</strong></p>
            <p>
              This application does not integrate any third-party advertising networks, social media tracking pixels, or external analytics platforms. All data remains within Chloride Exide Kenya's own infrastructure.
            </p>

            <p><strong>Your Rights</strong></p>
            <p>
              Under the <strong>Kenya Data Protection Act, 2019 (Act No. 24 of 2019)</strong> and the oversight of the
              Office of the Data Protection Commissioner (ODPC), you have the right to request access to, correction of,
              or deletion of any personal data we hold that is linked to you. You also have the right to lodge a complaint
              with the ODPC if you believe your data has been handled unlawfully. To make a data request, contact us at{' '}
              <a className="copyright-link" href="https://www.chlorideexide.com" target="_blank" rel="noopener noreferrer">
                www.chlorideexide.com
              </a>.
            </p>

            <p><strong>Changes to This Policy</strong></p>
            <p>
              We may update this policy periodically. Material changes will be reflected by an updated effective date above. Continued use of the Battery Finder after any update constitutes acceptance of the revised policy.
            </p>

          </div>
        </div>
      </div>
    </div>
  )
}
