import { unwrapDebugResponse } from '../debug/debug-envelope'
import { debugStore } from '../debug/debug-store'

export async function auronFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const response = await fetch(input, init)
  return unwrapDebugResponse(response, (entries) => debugStore.addEntries(entries))
}
