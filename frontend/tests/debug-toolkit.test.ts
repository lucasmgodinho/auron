import assert from 'node:assert/strict'
import test from 'node:test'

import { inspectDebugEnvelope, unwrapDebugResponse } from '../src/debug/debug-envelope.ts'
import { debugStore } from '../src/debug/debug-store.ts'
import type { DebugEntry } from '../src/debug/types.ts'

const firstEntry: DebugEntry = {
  type: 'value',
  label: 'Provider response',
  location: { file: 'backend/app/provider.py', function: 'execute', line: 42 },
  data: { result: true },
}

const stopEntry: DebugEntry = {
  type: 'stop',
  label: 'Stopped value',
  location: { file: 'backend/app/provider.py', function: 'execute', line: 45 },
  data: { stopped: true },
}

test('debug envelopes are detected and normal values are ignored', () => {
  assert.equal(inspectDebugEnvelope({ result: true }), null)
  assert.deepEqual(
    inspectDebugEnvelope({ _auron_payload: { result: true }, _auron_debug: [firstEntry] }),
    { _auron_payload: { result: true }, _auron_debug: [firstEntry] },
  )
})

test('successful responses are unwrapped and captured', async () => {
  const captured: DebugEntry[] = []
  const response = new Response(
    JSON.stringify({ _auron_payload: { result: 'ok' }, _auron_debug: [firstEntry] }),
    {
      status: 200,
      headers: {
        'Content-Type': 'Application/JSON; charset=utf-8',
        'X-Test': 'preserved',
      },
    },
  )

  const unwrapped = await unwrapDebugResponse(response, (entries) => captured.push(...entries))

  assert.equal(unwrapped.status, 200)
  assert.equal(unwrapped.headers.get('x-test'), 'preserved')
  assert.deepEqual(await unwrapped.json(), { result: 'ok' })
  assert.deepEqual(captured, [firstEntry])
})

test('failed responses preserve status while being unwrapped', async () => {
  const response = new Response(
    JSON.stringify({ _auron_payload: { detail: 'invalid' }, _auron_debug: [firstEntry] }),
    { status: 422, headers: { 'Content-Type': 'application/problem+json' } },
  )

  const unwrapped = await unwrapDebugResponse(response, () => undefined)

  assert.equal(unwrapped.ok, false)
  assert.equal(unwrapped.status, 422)
  assert.deepEqual(await unwrapped.json(), { detail: 'invalid' })
})

test('normal responses remain the same Response object', async () => {
  const response = new Response(JSON.stringify({ result: 'normal' }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

  assert.equal(await unwrapDebugResponse(response, () => undefined), response)
})

test('NDJSON responses remain open and available for progressive reading', async () => {
  const encoder = new TextEncoder()
  const decoder = new TextDecoder()
  const firstLine = `${JSON.stringify({ type: 'first' })}\n`
  const secondLine = `${JSON.stringify({ type: 'second' })}\n`
  let streamController: ReadableStreamDefaultController<Uint8Array> | undefined
  const response = new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        streamController = controller
        controller.enqueue(encoder.encode(firstLine))
      },
    }),
    { headers: { 'Content-Type': 'application/x-ndjson; charset=utf-8' } },
  )
  const unwrapPromise = unwrapDebugResponse(response, () => undefined)
  let timeout: ReturnType<typeof setTimeout> | undefined
  const timeoutPromise = new Promise<null>((resolve) => {
    timeout = setTimeout(() => resolve(null), 100)
  })

  const unwrapped = await Promise.race([unwrapPromise, timeoutPromise])
  if (timeout !== undefined) clearTimeout(timeout)
  if (unwrapped === null) {
    streamController?.close()
    await unwrapPromise
    assert.fail('NDJSON response waited for the stream to close')
  }

  assert.equal(unwrapped, response)
  assert.equal(unwrapped.bodyUsed, false)
  const reader = unwrapped.body?.getReader()
  assert.ok(reader)

  const firstChunk = await reader.read()
  assert.equal(firstChunk.done, false)
  assert.equal(decoder.decode(firstChunk.value), firstLine)

  streamController?.enqueue(encoder.encode(secondLine))
  const secondChunk = await reader.read()
  assert.equal(secondChunk.done, false)
  assert.equal(decoder.decode(secondChunk.value), secondLine)

  streamController?.close()
  assert.equal((await reader.read()).done, true)
})

test('the in-memory store consolidates, dismisses, reopens, and clears entries', () => {
  debugStore.clear()
  debugStore.addEntries([firstEntry])
  debugStore.addEntries([stopEntry])
  assert.deepEqual(debugStore.getSnapshot().entries, [firstEntry, stopEntry])
  assert.equal(debugStore.getSnapshot().dismissed, false)

  debugStore.dismiss()
  assert.equal(debugStore.getSnapshot().dismissed, true)

  debugStore.addEntries([firstEntry])
  assert.equal(debugStore.getSnapshot().dismissed, false)
  assert.equal(debugStore.getSnapshot().entries.length, 3)

  debugStore.clear()
  assert.deepEqual(debugStore.getSnapshot(), { entries: [], dismissed: false })
})
