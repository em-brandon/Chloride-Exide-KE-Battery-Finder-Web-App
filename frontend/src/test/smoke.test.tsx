import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

function Hello({ name }: { name: string }) {
  return <div>Hello, {name}!</div>
}

describe('vitest + RTL infra', () => {
  it('renders a component into jsdom', () => {
    render(<Hello name="World" />)
    expect(screen.getByText('Hello, World!')).toBeInTheDocument()
  })
})
