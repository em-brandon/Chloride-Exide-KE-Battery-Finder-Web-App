import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import AdminSettings from './AdminSettings'
import { getMaintenanceMode, setMaintenanceMode } from '@/lib/adminApi'

vi.mock('@/lib/adminApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/adminApi')>()
  return { ...actual, getMaintenanceMode: vi.fn(), setMaintenanceMode: vi.fn() }
})

function renderPage() {
  return render(<MemoryRouter><AdminSettings /></MemoryRouter>)
}

describe('AdminSettings', () => {
  beforeEach(() => {
    vi.mocked(getMaintenanceMode).mockReset()
    vi.mocked(setMaintenanceMode).mockReset()
  })

  it('shows "Turn ON" and status OFF when maintenance mode is disabled', async () => {
    vi.mocked(getMaintenanceMode).mockResolvedValue({ enabled: false })
    renderPage()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Turn ON' })).toBeInTheDocument())
    expect(screen.getByText('OFF')).toBeInTheDocument()
  })

  it('shows "Turn OFF", the ON status, and the visitor-facing banner when enabled', async () => {
    vi.mocked(getMaintenanceMode).mockResolvedValue({ enabled: true })
    renderPage()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Turn OFF' })).toBeInTheDocument())
    expect(screen.getByText('ON')).toBeInTheDocument()
    expect(screen.getByText(/currently showing the maintenance page/)).toBeInTheDocument()
  })

  it('toggles maintenance mode on click and reflects the new state', async () => {
    vi.mocked(getMaintenanceMode).mockResolvedValue({ enabled: false })
    vi.mocked(setMaintenanceMode).mockResolvedValue({ enabled: true })
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Turn ON' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Turn ON' }))

    expect(setMaintenanceMode).toHaveBeenCalledWith(true)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Turn OFF' })).toBeInTheDocument())
  })

  it('shows an error message when the toggle request fails', async () => {
    vi.mocked(getMaintenanceMode).mockResolvedValue({ enabled: false })
    vi.mocked(setMaintenanceMode).mockRejectedValue(new Error('network down'))
    const user = userEvent.setup()
    renderPage()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Turn ON' })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Turn ON' }))

    await waitFor(() => expect(screen.getByText('Failed to update maintenance mode.')).toBeInTheDocument())
    // State shouldn't have flipped since the request failed.
    expect(screen.getByRole('button', { name: 'Turn ON' })).toBeInTheDocument()
  })

  it('shows a load-error message when the initial fetch fails', async () => {
    vi.mocked(getMaintenanceMode).mockRejectedValue(new Error('down'))
    renderPage()
    await waitFor(() => expect(screen.getByText('Failed to load maintenance mode status.')).toBeInTheDocument())
  })
})
