import type { DebugEntry } from './types'

export type DebugState = {
  entries: readonly DebugEntry[]
  dismissed: boolean
}

const listeners = new Set<() => void>()
let state: DebugState = { entries: [], dismissed: false }

function emit() {
  for (const listener of listeners) listener()
}

export const debugStore = {
  subscribe(listener: () => void) {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
  getSnapshot() {
    return state
  },
  addEntries(entries: readonly DebugEntry[]) {
    if (entries.length === 0) return
    state = { entries: [...state.entries, ...entries], dismissed: false }
    emit()
  },
  dismiss() {
    if (state.dismissed || state.entries.length === 0) return
    state = { ...state, dismissed: true }
    emit()
  },
  clear() {
    if (state.entries.length === 0 && !state.dismissed) return
    state = { entries: [], dismissed: false }
    emit()
  },
}
