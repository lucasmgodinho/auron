import assert from 'node:assert/strict'
import test from 'node:test'

import { en } from '../src/i18n/locales/en.ts'
import { ptBR } from '../src/i18n/locales/pt-BR.ts'
import { isAnalysisRunCurrent } from '../src/modules/competitive_intelligence/analysis-run.ts'
import {
  CompetitiveIntelligenceStreamError,
  consumeAnalysisStream,
  parseAnalysisEvent,
  type AnalysisEvent,
} from '../src/modules/competitive_intelligence/stream-protocol.ts'

const occurredAt = '2026-09-08T12:00:00+00:00'

const started: AnalysisEvent = {
  type: 'analysis_started',
  occurred_at: occurredAt,
  data: { company_name: 'Tesla' },
}

const completed: AnalysisEvent = {
  type: 'analysis_completed',
  occurred_at: occurredAt,
  data: {
    company_name: 'Tesla',
    sector: 'Automotive',
    report: '# Report',
  },
}

function encode(event: object): string {
  return JSON.stringify(event)
}

function responseFromChunks(
  chunks: string[],
  contentType = 'application/x-ndjson; charset=utf-8',
): Response {
  const encoder = new TextEncoder()
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)))
        controller.close()
      },
    }),
    { headers: { 'Content-Type': contentType } },
  )
}

async function collectStream(chunks: string[]): Promise<AnalysisEvent[]> {
  const events: AnalysisEvent[] = []
  await consumeAnalysisStream(
    responseFromChunks(chunks),
    (event) => events.push(event),
  )
  return events
}

test('parses a line split across arbitrary chunks', async () => {
  const payload = `${encode(started)}\n${encode(completed)}\n`
  const events = await collectStream([
    payload.slice(0, 11),
    payload.slice(11, 37),
    payload.slice(37),
  ])
  assert.deepEqual(events, [started, completed])
})

test('parses multiple lines in one chunk', async () => {
  const events = await collectStream([`${encode(started)}\n${encode(completed)}\n`])
  assert.deepEqual(events, [started, completed])
})

test('parses the final line without a newline', async () => {
  const events = await collectStream([`${encode(started)}\n${encode(completed)}`])
  assert.deepEqual(events, [started, completed])
})

test('ignores blank lines and supports CRLF', async () => {
  const events = await collectStream([
    `\r\n${encode(started)}\r\n\r\n${encode(completed)}\r\n`,
  ])
  assert.deepEqual(events, [started, completed])
})

test('rejects an invalid payload for every event type', () => {
  const invalidEvents = [
    { type: 'analysis_started', data: { company_name: '' } },
    { type: 'questions_generated', data: { sector: 'Auto', questions: [] } },
    { type: 'search_started', data: { question: 'Q', current: 0, total: 1 } },
    {
      type: 'search_completed',
      data: {
        question: 'Q', current: 1, total: 1, sources: [], answer_indexed: 'yes',
      },
    },
    { type: 'search_failed', data: { question: 'Q', current: 1, total: 0 } },
    {
      type: 'documents_indexed',
      data: { documents: 1, embedding_units: 1, temporary: 'yes' },
    },
    { type: 'rag_retrieved', data: { retrieved_units: 1, retrieval_limit: 0 } },
    { type: 'report_generation_started', data: { company_name: 42 } },
    {
      type: 'analysis_completed',
      data: { company_name: 'Tesla', sector: 'Auto', report: '' },
    },
    { type: 'analysis_failed', data: { code: 'private_provider_error' } },
  ]

  invalidEvents.forEach((event) => {
    assert.throws(
      () => parseAnalysisEvent(encode({ ...event, occurred_at: occurredAt })),
      CompetitiveIntelligenceStreamError,
    )
  })
})

test('rejects unknown events, invalid timestamps, and unsafe source URLs', () => {
  assert.throws(
    () => parseAnalysisEvent(encode({ type: 'unknown', occurred_at: occurredAt, data: {} })),
    CompetitiveIntelligenceStreamError,
  )
  assert.throws(
    () => parseAnalysisEvent(encode({ ...started, occurred_at: 'not-a-timestamp' })),
    CompetitiveIntelligenceStreamError,
  )
  assert.throws(
    () => parseAnalysisEvent(encode({
      type: 'search_completed',
      occurred_at: occurredAt,
      data: {
        question: 'Q',
        current: 1,
        total: 1,
        sources: [{ title: 'Unsafe', url: 'javascript:alert(1)' }],
        answer_indexed: true,
      },
    })),
    CompetitiveIntelligenceStreamError,
  )
})

test('rejects a stream without a terminal event', async () => {
  await assert.rejects(
    consumeAnalysisStream(
      responseFromChunks([`${encode(started)}\n`]),
      () => undefined,
    ),
    (error: unknown) => error instanceof CompetitiveIntelligenceStreamError
      && error.code === 'stream_ended_unexpectedly',
  )
})

test('rejects an event after the terminal event', async () => {
  await assert.rejects(
    consumeAnalysisStream(
      responseFromChunks([`${encode(completed)}\n${encode(started)}\n`]),
      () => undefined,
    ),
    (error: unknown) => error instanceof CompetitiveIntelligenceStreamError
      && error.code === 'invalid_stream_event',
  )
})

test('delivers analysis_failed before throwing its public code', async () => {
  const failed: AnalysisEvent = {
    type: 'analysis_failed',
    occurred_at: occurredAt,
    data: { code: 'no_search_results' },
  }
  const events: AnalysisEvent[] = []

  await assert.rejects(
    consumeAnalysisStream(
      responseFromChunks([`${encode(failed)}\n`]),
      (event) => events.push(event),
    ),
    (error: unknown) => error instanceof CompetitiveIntelligenceStreamError
      && error.code === 'no_search_results',
  )
  assert.deepEqual(events, [failed])
})

test('honors AbortSignal and does not report it as a protocol failure', async () => {
  const controller = new AbortController()
  controller.abort()

  await assert.rejects(
    consumeAnalysisStream(
      responseFromChunks([`${encode(completed)}\n`]),
      () => undefined,
      controller.signal,
    ),
    (error: unknown) => error instanceof DOMException && error.name === 'AbortError',
  )
})

test('validates an NDJSON content type when the server provides one', async () => {
  await assert.rejects(
    consumeAnalysisStream(
      responseFromChunks([`${encode(completed)}\n`], 'application/json'),
      () => undefined,
    ),
    (error: unknown) => error instanceof CompetitiveIntelligenceStreamError
      && error.code === 'invalid_stream_response',
  )
})

function localeKeys(value: unknown, prefix = ''): string[] {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return [prefix]
  }
  return Object.entries(value).flatMap(([key, nested]) => (
    localeKeys(nested, prefix ? `${prefix}.${key}` : key)
  ))
}

test('pt-BR and English locales expose the same translation keys', () => {
  assert.deepEqual(localeKeys(ptBR).sort(), localeKeys(en).sort())
})

test('rejects stale, aborted, organization-changed, and unmounted analysis callbacks', () => {
  const current = {
    mounted: true,
    aborted: false,
    runId: 3,
    currentRunId: 3,
    organizationId: 'organization-a',
    currentOrganizationId: 'organization-a',
  }
  assert.equal(isAnalysisRunCurrent(current), true)
  assert.equal(isAnalysisRunCurrent({ ...current, mounted: false }), false)
  assert.equal(isAnalysisRunCurrent({ ...current, aborted: true }), false)
  assert.equal(isAnalysisRunCurrent({ ...current, currentRunId: 4 }), false)
  assert.equal(
    isAnalysisRunCurrent({ ...current, currentOrganizationId: 'organization-b' }),
    false,
  )
})
