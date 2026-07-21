import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import AdminLayout from './AdminLayout'
import { adminLogout } from '@/lib/adminApi'

vi.mock('@/lib/adminApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/adminApi')>()
  return { ...actual, adminLogout: vi.fn() }
})

function renderLayout(path = '/admin/dashboard') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AdminLayout><div>Page Content</div></AdminLayout>
    </MemoryRouter>
  )
}

describe('AdminLayout', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.mocked(adminLogout).mockReset().mockResolvedValue(undefined)
  })

  it('renders all nav items plus the page content', () => {
    renderLayout()
    expect(screen.getByText('Dashboard')).toBeInTheDocument()
    expect(screen.getByText('Batteries')).toBeInTheDocument()
    expect(screen.getByText('Data Pipeline')).toBeInTheDocument()
    expect(screen.getByText('Page Content')).toBeInTheDocument()
  })

  it('marks the nav link matching the current route as active (bold)', () => {
    renderLayout('/admin/batteries')
    const batteriesLink = screen.getByRole('link', { name: /batteries/i })
    const dashboardLink = screen.getByRole('link', { name: /dashboard/i })
    expect(batteriesLink).toHaveStyle({ fontWeight: 700 })
    expect(dashboardLink).toHaveStyle({ fontWeight: 500 })
  })

  it('auto-collapses the sidebar on a page in AUTO_COLLAPSE_PATHS', () => {
    renderLayout('/admin/feedback')
    expect(localStorage.getItem('sidebar_collapsed')).toBe('true')
  })

  it('toggles dark mode and persists the preference to localStorage', async () => {
    const user = userEvent.setup()
    renderLayout()
    expect(localStorage.getItem('admin_dark')).toBeNull()

    await user.click(screen.getByTitle('Switch to dark mode'))
    expect(localStorage.getItem('admin_dark')).toBe('1')
    expect(screen.getByTitle('Switch to light mode')).toBeInTheDocument()
  })

  it('toggles the sidebar collapse state and persists it', async () => {
    const user = userEvent.setup()
    renderLayout()
    await user.click(screen.getByTitle('Collapse sidebar'))
    expect(localStorage.getItem('sidebar_collapsed')).toBe('true')
    expect(localStorage.getItem('sidebar_manually_toggled')).toBe('true')
  })

  it('signs out via adminLogout when Sign Out is clicked', async () => {
    const user = userEvent.setup()
    renderLayout()
    await user.click(screen.getByText('Sign Out'))
    expect(adminLogout).toHaveBeenCalledOnce()
  })
})
