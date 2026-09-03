import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useTranslation } from 'react-i18next'

import { debugStore } from './debug-store'
import type { DebugEntry } from './types'

function entryValue(entry: DebugEntry): unknown {
  return Object.hasOwn(entry, 'data') ? entry.data : entry
}

function formatted(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? String(value)
  } catch {
    return String(value)
  }
}

function preview(entry: DebugEntry): string {
  const text = formatted(entryValue(entry)).replace(/\s+/g, ' ')
  return text.length > 140 ? `${text.slice(0, 140)}…` : text
}

function isTruncated(entry: DebugEntry): boolean {
  return formatted(entryValue(entry)).includes('"_auron_truncated": true')
}

async function copy(value: unknown): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(formatted(value))
    return true
  } catch {
    return false
  }
}

export function DebugNotification() {
  const { t } = useTranslation()
  const state = useSyncExternalStore(
    debugStore.subscribe,
    debugStore.getSnapshot,
    debugStore.getSnapshot,
  )
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [copiedKey, setCopiedKey] = useState<string | null>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const detailsTriggerRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLElement>(null)
  const latest = state.entries.at(-1)
  const stopped = state.entries.some((entry) => entry.type === 'stop')

  useEffect(() => {
    if (!detailsOpen) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeButtonRef.current?.focus()

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        closeDetails()
        return
      }
      if (event.key !== 'Tab' || !dialogRef.current) return
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), summary, [tabindex]:not([tabindex="-1"])',
        ),
      )
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [detailsOpen])

  useEffect(() => {
    if (state.entries.length === 0) setDetailsOpen(false)
  }, [state.entries.length])

  if (latest === undefined || state.dismissed) return null

  const latestLabel = latest.label || t(`developerDebug.types.${latest.type}`)
  const location = `${latest.location.file}:${latest.location.line}`

  async function copyWithFeedback(key: string, value: unknown) {
    if (await copy(value)) {
      setCopiedKey(key)
      window.setTimeout(() => setCopiedKey(null), 1_500)
    }
  }

  function closeDetails() {
    setDetailsOpen(false)
    window.setTimeout(() => detailsTriggerRef.current?.focus(), 0)
  }

  return (
    <>
      <aside
        className={`debug-notification${stopped ? ' debug-notification-stopped' : ''}`}
        aria-live="polite"
        aria-label={t('developerDebug.notificationLabel')}
      >
        <div className="debug-notification-heading">
          <span className="debug-notification-icon" aria-hidden="true">{'{ }'}</span>
          <div>
            <span>{stopped ? t('developerDebug.stopped') : t('developerDebug.development')}</span>
            <strong>{latestLabel}</strong>
          </div>
          <span className="debug-notification-count">{state.entries.length}</span>
        </div>
        <code className="debug-notification-location">{location}</code>
        <p>{preview(latest)}</p>
        <div className="debug-notification-actions">
          <button ref={detailsTriggerRef} className="text-button" type="button" onClick={() => setDetailsOpen(true)}>
            {t('developerDebug.viewDetails')}
          </button>
          <button
            className="text-button"
            type="button"
            onClick={() => void copyWithFeedback('latest', entryValue(latest))}
          >
            {t(copiedKey === 'latest' ? 'developerDebug.copied' : 'developerDebug.copyValue')}
          </button>
          <button className="text-button" type="button" onClick={() => debugStore.dismiss()}>
            {t('developerDebug.dismiss')}
          </button>
          <button className="text-button" type="button" onClick={() => debugStore.clear()}>
            {t('developerDebug.clearAll')}
          </button>
        </div>
      </aside>

      {detailsOpen ? (
        <div className="debug-dialog-layer">
          <button
            className="debug-dialog-overlay"
            type="button"
            aria-label={t('developerDebug.closeDetails')}
            onClick={closeDetails}
          />
          <section
            className="debug-dialog"
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="debug-dialog-title"
          >
            <header className="debug-dialog-header">
              <div>
                <p className="eyebrow">{t('developerDebug.development')}</p>
                <h2 id="debug-dialog-title">{t('developerDebug.detailsTitle')}</h2>
                <p>{t(state.entries.length === 1 ? 'developerDebug.entryCountOne' : 'developerDebug.entryCountMany', { count: state.entries.length })}</p>
              </div>
              <button
                ref={closeButtonRef}
                className="icon-button"
                type="button"
                aria-label={t('developerDebug.closeDetails')}
                onClick={closeDetails}
              >
                <span aria-hidden="true">×</span>
              </button>
            </header>
            <div className="debug-dialog-toolbar">
              <button
                className="button button-secondary"
                type="button"
                onClick={() => void copyWithFeedback('all', state.entries)}
              >
                {t(copiedKey === 'all' ? 'developerDebug.copied' : 'developerDebug.copyAll')}
              </button>
              <button className="button button-secondary" type="button" onClick={() => debugStore.clear()}>
                {t('developerDebug.clearAll')}
              </button>
            </div>
            <div className="debug-entry-list">
              {state.entries.map((entry, index) => (
                <details className={`debug-entry debug-entry-${entry.type}`} key={`${entry.location.file}-${entry.location.line}-${index}`} open={index === state.entries.length - 1}>
                  <summary>
                    <span className="debug-entry-index">{index + 1}</span>
                    <span><strong>{entry.label || t(`developerDebug.types.${entry.type}`)}</strong><code>{entry.location.file}:{entry.location.line}</code></span>
                    <span className="debug-entry-type">{entry.type}</span>
                  </summary>
                  <div className="debug-entry-body">
                    {isTruncated(entry) ? <span className="badge badge-warning">{t('developerDebug.truncated')}</span> : null}
                    <pre>{formatted(entryValue(entry))}</pre>
                    <button
                      className="text-button"
                      type="button"
                      onClick={() => void copyWithFeedback(`entry-${index}`, entryValue(entry))}
                    >
                      {t(copiedKey === `entry-${index}` ? 'developerDebug.copied' : 'developerDebug.copyEntry')}
                    </button>
                  </div>
                </details>
              ))}
            </div>
          </section>
        </div>
      ) : null}
    </>
  )
}
