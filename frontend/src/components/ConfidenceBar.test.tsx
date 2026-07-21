import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ConfidenceBar } from './ConfidenceBar'

describe('ConfidenceBar', () => {
  it('displays the numeric percentage', () => {
    render(<ConfidenceBar value={73} />)
    expect(screen.getByText('73%')).toBeInTheDocument()
  })

  it('uses emerald for a perfect 100% match', () => {
    const { container } = render(<ConfidenceBar value={100} />)
    expect(container.querySelector('.bg-emerald-400')).toBeInTheDocument()
  })

  it('uses orange for a soft match (60-99%)', () => {
    const { container } = render(<ConfidenceBar value={75} />)
    expect(container.querySelector('.bg-orange-400')).toBeInTheDocument()
  })

  it('uses violet for a low-confidence fallback match (<60%)', () => {
    const { container } = render(<ConfidenceBar value={40} />)
    expect(container.querySelector('.bg-violet-400')).toBeInTheDocument()
  })
})
