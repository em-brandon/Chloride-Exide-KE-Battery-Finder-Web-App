import { useEffect, useRef } from 'react'
import { XMarkIcon } from '@heroicons/react/24/outline'

interface BuildVersionModalProps {
  open: boolean
  onClose: () => void
}

export function BuildVersionModal({ open, onClose }: BuildVersionModalProps) {
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
      aria-label="Build Version"
    >
      <div className="faq-modal version-modal">
        <div className="faq-modal__header">
          <span className="faq-modal__title">Build Version</span>
          <button className="faq-modal__close" onClick={onClose} aria-label="Close">
            <XMarkIcon style={{ width: 18, height: 18 }} />
          </button>
        </div>
        <div className="faq-modal__body">
          <div className="version-modal__body">
            <div className="version-modal__row">
              <span className="version-modal__label">Version</span>
              <span className="version-modal__value">Beta v1.1.2</span>
            </div>
            <div className="version-modal__row">
              <span className="version-modal__label">Status</span>
              <span className="version-modal__badge">Beta — Pre-release</span>
            </div>
            <div className="version-modal__row">
              <span className="version-modal__label">Released</span>
              <span className="version-modal__value">9th June 2026</span>
            </div>
            <div className="version-modal__row">
              <span className="version-modal__label">Vehicle Data</span>
              <span className="version-modal__value">9th June 2026</span>
            </div>
            <p className="version-modal__note">
              This is a pre-release build of the Chloride Exide Battery Finder.
              Features, data, and recommendations are under active development and may change
              without notice. For issues or feedback, contact Chloride Exide Kenya at{' '}
              <a className="copyright-link" href="https://www.chlorideexide.com" target="_blank" rel="noopener noreferrer">
                www.chlorideexide.com
              </a>.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
