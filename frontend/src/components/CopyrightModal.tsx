import { useEffect, useRef } from 'react'
import { XMarkIcon } from '@heroicons/react/24/outline'

interface CopyrightModalProps {
  open: boolean
  onClose: () => void
}

export function CopyrightModal({ open, onClose }: CopyrightModalProps) {
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
      aria-label="Copyright Notice"
    >
      <div className="faq-modal">
        {/* Header */}
        <div className="faq-modal__header">
          <span className="faq-modal__title">Copyright &amp; Intellectual Property</span>
          <button className="faq-modal__close" onClick={onClose} aria-label="Close">
            <XMarkIcon style={{ width: 18, height: 18 }} />
          </button>
        </div>

        {/* Body */}
        <div className="faq-modal__body">
          <div className="faq-prose">

            <p className="copyright-year">&copy; 2026 Chloride Exide (Kenya) Limited. All rights reserved.</p>

            <p><strong>Ownership</strong></p>
            <p>
              The Chloride Exide Battery Finder — including its software, matching logic, user interface, design,
              vehicle fitment database, battery catalogue, and all associated content — is the exclusive proprietary
              property of <strong>Chloride Exide (Kenya) Limited</strong>. No part of this application may be
              reproduced, distributed, or transmitted in any form without prior written permission.
            </p>

            <p><strong>Permitted Use</strong></p>
            <p>
              This application is provided for personal, non-commercial use only. You may use it solely to
              identify a compatible battery recommendation for your own vehicle. Any other use requires express
              written authorisation from Chloride Exide (Kenya) Limited.
            </p>

            <p><strong>Prohibited Activities</strong></p>
            <ul className="faq-inner-list">
              <li>Copying, scraping, or bulk-extracting any data from this application by automated or manual means.</li>
              <li>Reverse engineering, decompiling, or attempting to derive the source code or underlying recommendation logic.</li>
              <li>Redistributing, sublicensing, selling, or commercially exploiting any content or data from this application.</li>
              <li>Framing or embedding this application within another website or application without written consent.</li>
              <li>Using this application in any way that violates applicable Kenyan law or international intellectual property treaties.</li>
            </ul>

            <p><strong>Trademarks</strong></p>
            <p>
              <strong>Chloride Exide</strong> and the Chloride Exide logo are registered trademarks of
              Chloride Exide (Kenya) Limited. All other product names, brand names, and trademarks referenced
              within this application are the property of their respective owners and are used for identification
              purposes only.
            </p>

            <p><strong>Vehicle &amp; Battery Data</strong></p>
            <p>
              Vehicle specification data is compiled from publicly available manufacturer records and proprietary
              Kenyan market fitment data. The battery catalogue reflects Chloride Exide Kenya's active product
              range. Unauthorised extraction or commercial use of this data is strictly prohibited.
            </p>

            <p><strong>Data Protection</strong></p>
            <p>
              This application is operated in compliance with the <strong>Kenya Data Protection Act, 2019 (Act No. 24 of 2019)</strong>{' '}
              and is subject to the oversight of the Office of the Data Protection Commissioner (ODPC). The only personal
              data collected by this application is the IP address submitted alongside voluntary user feedback, retained
              solely for spam prevention and service quality purposes. No personal account data, email addresses, or
              payment information is collected through the public-facing application. Data collected is never sold,
              rented, or shared with third parties for commercial purposes.
            </p>

            <p><strong>Governing Law</strong></p>
            <p>
              This application and all matters relating to its use are governed by the laws of the
              Republic of Kenya. Any disputes shall be subject to the exclusive jurisdiction of the
              Kenyan courts.
            </p>

            <p><strong>Contact &amp; Registered Office</strong></p>
            <p>
              Chloride Exide (Kenya) Limited<br />
              Exans House, off Enterprise Road<br />
              Industrial Area, Nairobi, Kenya
            </p>
            <p>
              For licensing enquiries, permissions, or intellectual property concerns, visit{' '}
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
