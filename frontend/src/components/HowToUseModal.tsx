import { useEffect, useRef } from 'react'
import { XMarkIcon } from '@heroicons/react/24/outline'

interface HowToUseModalProps {
  open: boolean
  onClose: () => void
}

export function HowToUseModal({ open, onClose }: HowToUseModalProps) {
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
      aria-label="How to Use the Battery Finder"
    >
      <div className="faq-modal">
        <div className="faq-modal__header">
          <span className="faq-modal__title">How to Use the Battery Finder</span>
          <button className="faq-modal__close" onClick={onClose} aria-label="Close">
            <XMarkIcon style={{ width: 18, height: 18 }} />
          </button>
        </div>

        <div className="faq-modal__body">
          <div className="faq-prose">

            <p>Follow these steps to get the right battery recommendation for your vehicle:</p>

            <p><strong>Step 1 — Select your Make</strong></p>
            <p>
              Choose the brand of your vehicle from the dropdown — e.g. Toyota, Nissan, Subaru, or Mercedes-Benz.
              If your make isn't in the list, switch to <em>Type mode</em> using the toggle at the top of the form.
            </p>

            <p><strong>Step 2 — Select your Model</strong></p>
            <p>
              Pick the specific model of your vehicle — e.g. Corolla, Hilux, Forester, or C-Class.
              If you don't see your model in the dropdown, use the <em>"Type your query instead"</em> hint to switch to manual entry.
            </p>

            <p><strong>Step 3 — Select the Year</strong></p>
            <p>
              Choose the year your vehicle was manufactured. If you're unsure, check your logbook or the sticker inside the driver's door frame.
            </p>

            <p><strong>Step 4 — Find your Battery</strong></p>
            <p>
              Click <strong>Find Battery</strong>. Your result includes a <strong>Result Accuracy</strong> bar — a coloured strip that shows how confident the system is in the recommendation. Each colour represents a different factor:
            </p>
            <ul className="faq-inner-list">
              <li>
                <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', background: '#10b981', marginRight: 6, verticalAlign: 'middle' }} />
                <strong>Car Found (green)</strong> — the largest segment. Fully filled when your make and model were found in our records; empty when the result is based on engine size only.
              </li>
              <li>
                <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', background: '#3b82f6', marginRight: 6, verticalAlign: 'middle' }} />
                <strong>Year (blue)</strong> — how closely your year matched. Fully filled for an exact year; lower if the nearest available year was used.
              </li>
              <li>
                <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', background: '#8b5cf6', marginRight: 6, verticalAlign: 'middle' }} />
                <strong>Data Quality (purple)</strong> — whether the result is backed by real-world fitment records, our structured database, or a rule-based engine estimate.
              </li>
              <li>
                <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', background: '#f59e0b', marginRight: 6, verticalAlign: 'middle' }} />
                <strong>Engine Info (amber)</strong> — whether your engine details were confirmed from our records or inferred.
              </li>
            </ul>
            <p>
              A fuller bar means a more reliable recommendation. If an amber warning appears at the top of the result card, your model wasn't found — treat the result as an estimate and confirm with a Chloride Exide dealer before purchasing.
            </p>

            <p><strong>Optional — Engine Size &amp; Fuel Type</strong></p>
            <p>
              Providing your engine size (CC) and fuel type improves fallback accuracy. You can find your engine size on your registration document, the dashboard sticker, or the engine bay label. Common sizes: 1000, 1300, 1500, 1800, 2000, 2500, 3000 cc.
            </p>

            <p><strong>Optional — i-stop / Start-Stop</strong></p>
            <p>
              If your vehicle has an i-stop or start-stop system (a button or indicator on the dashboard), toggle it ON. This ensures the app recommends an EFB or AGM battery, which is required for start-stop vehicles. Using a standard battery in a start-stop car will significantly shorten its lifespan.
            </p>

          </div>
        </div>
      </div>
    </div>
  )
}
