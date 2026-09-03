import type { DebugEntry, DebugEnvelope } from './types'

const DEBUG_ENTRY_TYPES = new Set(['value', 'snapshot', 'mark', 'timer', 'exception', 'stop'])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isDebugEntry(value: unknown): value is DebugEntry {
  if (!isRecord(value) || typeof value.type !== 'string' || !DEBUG_ENTRY_TYPES.has(value.type)) {
    return false
  }
  const location = value.location
  return isRecord(location)
    && typeof location.file === 'string'
    && typeof location.function === 'string'
    && typeof location.line === 'number'
}

export function inspectDebugEnvelope(value: unknown): DebugEnvelope | null {
  if (!isRecord(value) || !Object.hasOwn(value, '_auron_payload')) return null
  if (!Array.isArray(value._auron_debug) || !value._auron_debug.every(isDebugEntry)) return null
  return {
    _auron_payload: value._auron_payload,
    _auron_debug: value._auron_debug,
  }
}

export async function unwrapDebugResponse(
  response: Response,
  capture: (entries: readonly DebugEntry[]) => void,
): Promise<Response> {
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? ''
  if (!contentType.includes('json') || response.status === 204 || response.status === 304) {
    return response
  }

  let body: unknown
  try {
    body = await response.clone().json()
  } catch {
    return response
  }
  const envelope = inspectDebugEnvelope(body)
  if (envelope === null) return response

  capture(envelope._auron_debug)
  const headers = new Headers(response.headers)
  headers.delete('content-length')
  return new Response(JSON.stringify(envelope._auron_payload), {
    status: response.status,
    statusText: response.statusText,
    headers,
  })
}
