import { useState, useEffect, useRef } from 'react'
import { XMarkIcon } from '@heroicons/react/24/outline'

interface FaqModalProps {
  open: boolean
  onClose: () => void
  initialTab?: Tab
  singleTab?: boolean
}

type Tab = 'faq' | 'how' | 'disclaimer'

const FAQ_ITEMS: { q: string; a: React.ReactNode }[] = [
  {
    q: 'How does the Battery Finder work?',
    a: 'The Battery Finder checks your vehicle against a database of thousands of make/model/year combinations used in Kenya. It first tries to find your exact vehicle and recommend the battery most commonly fitted to it by our dealers. If your exact model or year isn\'t found, it looks for the closest match in the same model family. As a last resort, it uses your engine size and fuel type to estimate the right battery size.',
  },
  {
    q: 'What does the Result Accuracy bar show?',
    a: (
      <span>
        The Result Accuracy bar is a coloured strip below your battery recommendation. It breaks down how confident the system is across four factors:
        <ul className="faq-inner-list">
          <li>
            <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', background: '#10b981', marginRight: 6, verticalAlign: 'middle' }} />
            <strong>Car Found (green)</strong> — the largest segment. Fully filled when your make and model are in our records; empty when the result falls back to an engine-size estimate.
          </li>
          <li>
            <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', background: '#3b82f6', marginRight: 6, verticalAlign: 'middle' }} />
            <strong>Year (blue)</strong> — how closely your year matched. Fully filled for an exact year; lower if the nearest available year was used.
          </li>
          <li>
            <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', background: '#8b5cf6', marginRight: 6, verticalAlign: 'middle' }} />
            <strong>Data Quality (purple)</strong> — whether the result came from real-world fitment records, our structured database, or an engine-size estimate.
          </li>
          <li>
            <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', background: '#f59e0b', marginRight: 6, verticalAlign: 'middle' }} />
            <strong>Engine Info (amber)</strong> — whether your engine details were confirmed in our database or inferred.
          </li>
        </ul>
        A fuller bar means a more reliable result. If an amber warning appears at the top of the result card, your model wasn't found — the recommendation is an estimate; confirm with a Chloride Exide dealer before purchasing.
      </span>
    ),
  },
  {
    q: 'What is Ah (Ampere-hours)?',
    a: 'Ah is the battery\'s energy capacity — how long it can supply power to your car\'s electronics before needing a recharge from the alternator. A higher Ah battery stores more energy. Always use the recommended Ah or above; never go lower.',
  },
  {
    q: 'What is CCA (Cold Cranking Amps)?',
    a: 'CCA measures the burst of power the battery can deliver to start your engine. A higher CCA means stronger starting ability. In Kenya\'s warm climate, CCA is less of a concern than in cold-weather countries, but it still reflects overall battery quality and reliable starting performance.',
  },
  {
    q: 'What is i-stop / Stop-Start technology?',
    a: 'i-stop (also called Stop-Start or ISS) is a fuel-saving system that automatically shuts off the engine when the car is at a standstill — at traffic lights, for example — and restarts it instantly when you move off. Vehicles fitted with this system require a special EFB or AGM battery. Installing a standard (MF) battery in a stop-start vehicle will cause it to fail prematurely within months due to the much higher charge/discharge cycling.',
  },
  {
    q: 'What is the difference between AGM, EFB, and MF batteries?',
    a: (
      <span>
        <ul className="faq-inner-list">
          <li><strong>AGM (Absorbent Glass Mat):</strong> The premium standard. Required for luxury vehicles, large diesel engines, and any vehicle with heavy electrical loads. Handles high charge cycling.</li>
          <li><strong>EFB (Enhanced Flooded Battery):</strong> Mid-range. The correct choice for most modern stop-start vehicles. More durable than standard batteries under stop-start cycling conditions.</li>
          <li><strong>MF (Maintenance-Free):</strong> The standard sealed battery for conventional vehicles without stop-start. No water top-up needed. Not suitable for stop-start systems.</li>
        </ul>
      </span>
    ),
  },
  {
    q: 'My car model wasn\'t found — what should I do?',
    a: 'Try entering your model name differently. For example, type "HILUX" instead of "TOYOTA HILUX", or "CX 5" instead of "CX-5". If the Result Accuracy bar is still low, the recommendation is still a reasonable starting point — visit your nearest Chloride Exide dealer who can physically inspect your vehicle and confirm the correct battery.',
  },
  {
    q: 'Can I use a battery with a higher Ah than recommended?',
    a: 'Generally yes. A battery one size higher in Ah is acceptable as long as it physically fits your battery tray and has the correct terminal type (NS or DIN) and terminal orientation. Never install a battery with a lower Ah than recommended — it may not meet your vehicle\'s power demands and will shorten battery life.',
  },
  {
    q: 'What is the difference between NS and DIN batteries?',
    a: 'NS batteries (also called JIS) are the standard for Japanese, Korean, and Chinese vehicles — Toyota, Honda, Nissan, Mazda, Hyundai, Kia, etc. DIN batteries are the standard for European and American vehicles — BMW, Mercedes-Benz, Volkswagen, Ford, Peugeot, etc. The two types have different physical dimensions and terminal positions and are not interchangeable. The Battery Finder automatically selects the correct type based on your vehicle\'s make.',
  },
  {
    q: 'How current is the vehicle and battery data?',
    a: 'The vehicle database is refreshed periodically to include new models entering the Kenyan market. The battery catalogue reflects Chloride Exide Kenya\'s active product range. For very new vehicles or the latest battery availability, contact your nearest Chloride Exide dealer directly.',
  },
  {
    q: 'How long should a car battery last, and when should I replace it?',
    a: (
      <span>
        In Kenya's climate, a well-maintained car battery typically lasts <strong>3 to 5 years</strong>. Heat accelerates battery wear, so batteries in vehicles with poor engine-bay ventilation or that spend long periods idling may need replacement sooner. Replace your battery if you notice any of the following:
        <ul className="faq-inner-list">
          <li>Slow or sluggish cranking on startup — especially in the morning</li>
          <li>Headlights or interior lights dimming when you turn the key</li>
          <li>Battery warning light appearing on your dashboard</li>
          <li>The battery is more than 4 years old</li>
          <li>The car needed a jump-start more than once in a short period</li>
        </ul>
        Don't wait for a complete failure — a flat battery in traffic or away from town is costly and dangerous.
      </span>
    ),
  },
  {
    q: 'What does the "Alternative Battery" shown on my result mean?',
    a: 'The alternative is a different battery with the same or compatible specifications that will also fit your vehicle. It\'s your second option if the primary recommendation is out of stock, or if you want to compare pricing between product lines. Both batteries are suitable — the primary is simply the most commonly supplied for your vehicle by Chloride Exide dealers across Kenya.',
  },
  {
    q: 'My car is a JDM import (Vitz, Fielder, Allion, Premio, Demio, etc.) — will it be found?',
    a: 'Yes. The database includes the Japanese domestic market (JDM) model names used on grey imports that are common across Kenya. If your result shows a low accuracy, try the Japanese model name — for example, search "VITZ" rather than "YARIS", or "FIELDER" rather than "COROLLA WAGON". JDM vehicles automatically receive the NS/JIS battery standard, which is correct for all Japanese-market cars.',
  },
  {
    q: 'Can I search by battery Ah or CCA instead of my vehicle details?',
    a: 'Yes. Use the "Search by Battery Specs" tab (on desktop) and enter the Ah or CCA value printed on your existing battery label. This is useful when your vehicle isn\'t in the database, when replacing a battery on a non-standard or modified vehicle, or when you simply want to find a compatible replacement for an existing battery by specification.',
  },
  {
    q: 'What is the warranty on Chloride Exide batteries?',
    a: 'Warranty periods vary by product line and are confirmed at the point of purchase. Always keep your purchase receipt — it is required for any warranty claim. Bring both the receipt and the battery to the dealer where it was purchased. Warranty covers manufacturing defects and does not cover damage from incorrect installation, deep discharge, or use in a vehicle with a faulty charging system.',
  },
  {
    q: 'Where can I buy the recommended battery?',
    a: (
      <span>
        Use the <strong>Shop Now</strong> button on the result card to visit the Chloride Exide Kenya online store. You can also call the <strong>Dial-a-Battery</strong> service shown at the bottom of your result for home or roadside delivery in major Kenyan towns. To find your nearest dealer branch, visit{' '}
        <a href="https://www.chlorideexide.com" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--blue, #005794)', fontWeight: 600 }}>
          chlorideexide.com
        </a>.
      </span>
    ),
  },
  {
    q: 'How do I dispose of my old battery?',
    a: 'Car batteries contain lead and sulphuric acid — they must never be disposed of in household waste or dumped. Return your old battery to any Chloride Exide dealer or licensed auto parts outlet. Most dealers accept old batteries for recycling and may offer a trade-in credit toward your new purchase. Proper recycling recovers up to 99% of the lead for reuse and prevents soil and water contamination.',
  },
]

function AccordionItem({ q, a }: { q: string; a: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="faq-item">
      <button className="faq-item__q" onClick={() => setOpen(o => !o)} aria-expanded={open}>
        <span className="faq-item__chevron">{open ? '▾' : '▸'}</span>
        {q}
      </button>
      {open && <div className="faq-item__a">{a}</div>}
    </div>
  )
}

export function FaqModal({ open, onClose, initialTab, singleTab }: FaqModalProps) {
  const [tab, setTab] = useState<Tab>(initialTab ?? 'faq')
  const overlayRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // Reset to the appropriate tab each time modal opens
  useEffect(() => {
    if (open) setTab(initialTab ?? 'faq')
  }, [open, initialTab])

  if (!open) return null

  return (
    <div
      className="faq-overlay"
      ref={overlayRef}
      onMouseDown={e => { if (e.target === overlayRef.current) onClose() }}
      role="dialog"
      aria-modal="true"
      aria-label="FAQ and Disclaimer"
    >
      <div className="faq-modal">
        {/* Header */}
        <div className="faq-modal__header">
          <span className="faq-modal__title">
            {singleTab ? 'Disclaimer' : 'FAQ & Disclaimer'}
          </span>
          <button className="faq-modal__close" onClick={onClose} aria-label="Close">
            <XMarkIcon style={{ width: 18, height: 18 }} />
          </button>
        </div>

        {/* Tabs — hidden when opened in single-tab (disclaimer-only) mode */}
        {!singleTab && (
          <div className="faq-tabs" role="tablist">
            <button
              role="tab"
              aria-selected={tab === 'faq'}
              className={`faq-tab${tab === 'faq' ? ' faq-tab--active' : ''}`}
              onClick={() => setTab('faq')}
            >
              FAQ
            </button>
            <button
              role="tab"
              aria-selected={tab === 'how'}
              className={`faq-tab${tab === 'how' ? ' faq-tab--active' : ''}`}
              onClick={() => setTab('how')}
            >
              How It Works
            </button>
            <button
              role="tab"
              aria-selected={tab === 'disclaimer'}
              className={`faq-tab${tab === 'disclaimer' ? ' faq-tab--active' : ''}`}
              onClick={() => setTab('disclaimer')}
            >
              Disclaimer
            </button>
          </div>
        )}

        {/* Body */}
        <div className="faq-modal__body">
          {tab === 'faq' && (
            <div>
              {FAQ_ITEMS.map((item, i) => (
                <AccordionItem key={i} q={item.q} a={item.a} />
              ))}
            </div>
          )}

          {tab === 'how' && (
            <div className="faq-prose">
              <p>When you enter your vehicle details, the Battery Finder searches in three steps — from most accurate to least:</p>
              <ol className="faq-steps">
                <li>
                  <strong>Database Lookup</strong> — We search our database for your exact make, model, and year. If found, we recommend the battery most commonly supplied to that vehicle by Chloride Exide dealers across Kenya, backed by real sales records.
                </li>
                <li>
                  <strong>Close Match</strong> — If your exact year isn't in our records, we find the nearest model year within a small window and use that vehicle's battery specification.
                </li>
                <li>
                  <strong>Smart Estimate</strong> — If we can't find your model at all, we use your engine size and fuel type to calculate an appropriate battery size. This is less precise, but gives you a solid starting point.
                </li>
              </ol>
              <p>
                The <strong>Result Accuracy</strong> bar below your recommendation shows how closely each factor matched —{' '}
                <span style={{ color: '#10b981', fontWeight: 600 }}>green</span> for whether your car was found,{' '}
                <span style={{ color: '#3b82f6', fontWeight: 600 }}>blue</span> for year match,{' '}
                <span style={{ color: '#8b5cf6', fontWeight: 600 }}>purple</span> for data quality, and{' '}
                <span style={{ color: '#f59e0b', fontWeight: 600 }}>amber</span> for engine info. A fuller bar means a more reliable recommendation.
              </p>
              <p>
                The tool also automatically determines whether your vehicle uses the <strong>NS/JIS</strong> standard (Japanese, Korean, and Chinese makes) or the <strong>DIN</strong> standard (European and American makes), and whether an <strong>AGM</strong>, <strong>EFB</strong>, or standard <strong>MF</strong> battery is appropriate based on stop-start technology and engine characteristics.
              </p>
            </div>
          )}

          {tab === 'disclaimer' && (
            <div className="faq-prose faq-disclaimer">
              <p className="faq-disclaimer__lead">
                <strong>Important — Please Read Before Acting on Any Recommendation</strong>
              </p>
              <p>
                The Chloride Exide Battery Finder provides recommendations based on vehicle specification data and real-world fitment records. These recommendations are intended as a <strong>starting guide only</strong> and do not replace the judgement of a qualified automotive technician or Chloride Exide dealer.
              </p>

              <p><strong>Accuracy of Results</strong></p>
              <ul className="faq-inner-list">
                <li>Results depend entirely on the accuracy of the vehicle details you provide. Incorrect make, model, year, engine size, or fuel type will produce unreliable recommendations.</li>
                <li>A lower Result Accuracy bar indicates the result is an estimate — professional verification is especially important in these cases.</li>
                <li>Actual battery requirements may vary due to aftermarket electrical modifications, non-standard accessories, or grey-import vehicles with specifications not reflected in our database.</li>
              </ul>

              <p><strong>Before Purchase &amp; Installation</strong></p>
              <ul className="faq-inner-list">
                <li>Always verify <strong>physical dimensions</strong>, <strong>terminal polarity</strong>, and <strong>terminal position</strong> before purchasing or installing any battery.</li>
                <li>Ensure the battery fits your vehicle's battery tray without modification. An ill-fitting battery can vibrate loose and cause electrical damage.</li>
                <li>Battery installation should be carried out by a qualified technician. Incorrect installation — including reversed polarity — can permanently damage your vehicle's electrical system, trigger airbag deployment, or void the battery warranty.</li>
                <li>For electric (EV) and hybrid vehicles, this tool recommends the <strong>12V auxiliary battery only</strong> — not the main traction (high-voltage) battery pack.</li>
              </ul>

              <p><strong>Data Currency</strong></p>
              <ul className="faq-inner-list">
                <li>The vehicle database and battery catalogue are updated periodically but may not immediately reflect the very latest model-year releases or recently discontinued battery lines.</li>
                <li>For vehicles launched within the last 12 months, we recommend confirming the recommendation with a Chloride Exide dealer directly.</li>
              </ul>

              <p><strong>Pricing &amp; Availability</strong></p>
              <ul className="faq-inner-list">
                <li>This tool does not display pricing. Battery prices vary by dealer, location, and market conditions — contact your nearest dealer for a current quote.</li>
                <li>Stock availability is not guaranteed. A recommended battery code may be temporarily out of stock; alternatives shown carry equivalent specifications.</li>
              </ul>

              <p><strong>Limitation of Liability</strong></p>
              <ul className="faq-inner-list">
                <li className="flash-liability" style={{ color: '#CC0000', fontWeight: 700 }}>Chloride Exide Kenya accepts no liability for damage, loss, or any adverse outcome arising from reliance on these recommendations without professional verification.</li>
                <li>This tool is intended for use within Kenya. Recommendations are based on vehicle fitments and battery standards applicable to the Kenyan market and may not be appropriate for other regions.</li>
              </ul>

              <p>
                For any uncertainty, visit your nearest <strong>Chloride Exide dealer</strong> for a hands-on battery assessment.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
