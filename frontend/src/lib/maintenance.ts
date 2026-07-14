/**
 * maintenance.ts — detect the maintenance-mode response so an already-loaded
 * SPA tab reacts to it correctly.
 *
 * The backend's maintenance middleware (backend/app.py) intercepts every
 * non-admin request and returns maintenance.html with a 503 status when
 * maintenance mode is on. That only reaches users making a fresh top-level
 * page request — an already-open tab just keeps making background fetch()
 * calls, which get this same 503+HTML response instead of the JSON they
 * expect. Without detecting it explicitly, callers were treating that as a
 * generic failure (or worse, a login failure — see TestUserContext), when
 * what actually needs to happen is a full page reload so the browser makes
 * a fresh top-level request the backend middleware can correctly intercept
 * and serve the real maintenance page for.
 */

export function isMaintenanceResponse(res: Response): boolean {
  return res.status === 503 && (res.headers.get('content-type') ?? '').includes('text/html')
}

export function redirectToMaintenance(): never {
  window.location.reload()
  // reload() doesn't halt execution — throw so callers stop using stale state.
  throw new Error('Service is in maintenance mode')
}
