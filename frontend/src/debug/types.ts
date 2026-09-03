export type DebugLocation = {
  file: string
  function: string
  line: number
}

export type DebugEntryType = 'value' | 'snapshot' | 'mark' | 'timer' | 'exception' | 'stop'

export type DebugEntry = {
  type: DebugEntryType
  label: string | null
  location: DebugLocation
  data?: unknown
}

export type DebugEnvelope = {
  _auron_payload: unknown
  _auron_debug: DebugEntry[]
}
