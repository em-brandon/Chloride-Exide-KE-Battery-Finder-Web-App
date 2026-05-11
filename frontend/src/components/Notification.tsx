import { useEffect, useState } from 'react'
import { CheckCircleIcon, XCircleIcon, XMarkIcon } from '@heroicons/react/20/solid'

export interface ToastItem {
  id: number
  type: 'success' | 'error'
  title: string
  description?: string
}

interface ToastProps {
  item: ToastItem
  onDismiss: (id: number) => void
}

function Toast({ item, onDismiss }: ToastProps) {
  const [out, setOut] = useState(false)

  useEffect(() => {
    const dismiss = () => { setOut(true); setTimeout(() => onDismiss(item.id), 300) }
    const t = setTimeout(dismiss, 2000)
    return () => clearTimeout(t)
  }, [item.id, onDismiss])

  const handleClose = () => {
    setOut(true)
    setTimeout(() => onDismiss(item.id), 300)
  }

  return (
    <div className={`toast ${item.type}${out ? ' out' : ''}`} role="alert">
      <span className="toast-icon">
        {item.type === 'success'
          ? <CheckCircleIcon style={{ width: 18, height: 18 }} />
          : <XCircleIcon style={{ width: 18, height: 18 }} />}
      </span>
      <div className="toast-body">
        <div className="toast-title">{item.title}</div>
        {item.description && (
          <div className="toast-desc">{item.description}</div>
        )}
      </div>
      <button className="toast-close" onClick={handleClose} aria-label="Dismiss">
        <XMarkIcon style={{ width: 14, height: 14 }} />
      </button>
    </div>
  )
}

interface ToasterProps {
  items: ToastItem[]
  onDismiss: (id: number) => void
}

export function Toaster({ items, onDismiss }: ToasterProps) {
  return (
    <div className="toast-wrap" aria-live="polite">
      {items.map(item => (
        <Toast key={item.id} item={item} onDismiss={onDismiss} />
      ))}
    </div>
  )
}

let _toastId = 0
export function useToast() {
  const [toasts, setToasts] = useState<ToastItem[]>([])

  const push = (type: 'success' | 'error', title: string, description?: string) => {
    const id = ++_toastId
    setToasts(prev => [...prev, { id, type, title, description }])
  }

  const dismiss = (id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }

  return { toasts, push, dismiss }
}
