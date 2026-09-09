export type CompetitiveAnalysis = {
  company_name: string
  sector: string
  report: string
}

export const ANALYSIS_FAILURE_CODES = [
  "invalid_company",
  "no_search_results",
  "search_provider_failed",
  "model_provider_failed",
  "vector_store_failed",
  "unexpected_error",
] as const

export type AnalysisFailureCode = typeof ANALYSIS_FAILURE_CODES[number]

type AnalysisEventBase<Type extends string, Data> = {
  type: Type
  occurred_at: string
  data: Data
}

export type AnalysisEvent =
  | AnalysisEventBase<"analysis_started", { company_name: string }>
  | AnalysisEventBase<
    "questions_generated",
    { sector: string; questions: string[] }
  >
  | AnalysisEventBase<
    "search_started",
    { question: string; current: number; total: number }
  >
  | AnalysisEventBase<
    "search_completed",
    {
      question: string
      current: number
      total: number
      sources: Array<{ title: string; url: string }>
      answer_indexed: boolean
    }
  >
  | AnalysisEventBase<
    "search_failed",
    { question: string; current: number; total: number }
  >
  | AnalysisEventBase<
    "documents_indexed",
    { documents: number; embedding_units: number; temporary: boolean }
  >
  | AnalysisEventBase<
    "rag_retrieved",
    { retrieved_units: number; retrieval_limit: number }
  >
  | AnalysisEventBase<"report_generation_started", { company_name: string }>
  | AnalysisEventBase<"analysis_completed", CompetitiveAnalysis>
  | AnalysisEventBase<"analysis_failed", { code: AnalysisFailureCode }>

export class CompetitiveIntelligenceStreamError extends Error {
  code: string

  constructor(code: string) {
    super(`Competitive Intelligence stream failed: ${code}`)
    this.name = "CompetitiveIntelligenceStreamError"
    this.code = code
  }
}

type UnknownRecord = Record<string, unknown>

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function requiredString(data: UnknownRecord, key: string): string {
  const value = data[key]
  if (typeof value !== "string" || !value.trim()) {
    throw new CompetitiveIntelligenceStreamError("invalid_stream_event")
  }
  return value
}

function requiredInteger(
  data: UnknownRecord,
  key: string,
  minimum: number,
): number {
  const value = data[key]
  if (
    typeof value !== "number"
    || !Number.isFinite(value)
    || !Number.isInteger(value)
    || value < minimum
  ) {
    throw new CompetitiveIntelligenceStreamError("invalid_stream_event")
  }
  return value
}

function requiredProgress(data: UnknownRecord) {
  const question = requiredString(data, "question")
  const current = requiredInteger(data, "current", 1)
  const total = requiredInteger(data, "total", 1)
  if (current > total) {
    throw new CompetitiveIntelligenceStreamError("invalid_stream_event")
  }
  return { question, current, total }
}

function isSafeHttpUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return (url.protocol === "http:" || url.protocol === "https:")
      && Boolean(url.hostname)
      && !url.username
      && !url.password
  } catch {
    return false
  }
}

function requiredTimestamp(value: unknown): string {
  if (
    typeof value !== "string"
    || !/(?:Z|[+-]00:00)$/u.test(value)
    || !Number.isFinite(Date.parse(value))
  ) {
    throw new CompetitiveIntelligenceStreamError("invalid_stream_event")
  }
  return value
}

export function parseAnalysisEvent(line: string): AnalysisEvent {
  let value: unknown
  try {
    value = JSON.parse(line)
  } catch {
    throw new CompetitiveIntelligenceStreamError("invalid_stream_event")
  }

  if (!isRecord(value) || !isRecord(value.data)) {
    throw new CompetitiveIntelligenceStreamError("invalid_stream_event")
  }

  const occurred_at = requiredTimestamp(value.occurred_at)
  const data = value.data
  switch (value.type) {
    case "analysis_started":
      return {
        type: value.type,
        occurred_at,
        data: { company_name: requiredString(data, "company_name") },
      }
    case "questions_generated": {
      const questions = data.questions
      if (
        !Array.isArray(questions)
        || questions.length === 0
        || !questions.every((question) => (
          typeof question === "string" && Boolean(question.trim())
        ))
      ) {
        throw new CompetitiveIntelligenceStreamError("invalid_stream_event")
      }
      return {
        type: value.type,
        occurred_at,
        data: {
          sector: requiredString(data, "sector"),
          questions,
        },
      }
    }
    case "search_started":
    case "search_failed":
      return { type: value.type, occurred_at, data: requiredProgress(data) }
    case "search_completed": {
      const sources = data.sources
      if (!Array.isArray(sources)) {
        throw new CompetitiveIntelligenceStreamError("invalid_stream_event")
      }
      const validatedSources = sources.map((source) => {
        if (!isRecord(source)) {
          throw new CompetitiveIntelligenceStreamError("invalid_stream_event")
        }
        const title = requiredString(source, "title")
        const url = requiredString(source, "url")
        if (!isSafeHttpUrl(url)) {
          throw new CompetitiveIntelligenceStreamError("invalid_stream_event")
        }
        return { title, url }
      })
      if (typeof data.answer_indexed !== "boolean") {
        throw new CompetitiveIntelligenceStreamError("invalid_stream_event")
      }
      return {
        type: value.type,
        occurred_at,
        data: {
          ...requiredProgress(data),
          sources: validatedSources,
          answer_indexed: data.answer_indexed,
        },
      }
    }
    case "documents_indexed":
      if (typeof data.temporary !== "boolean") {
        throw new CompetitiveIntelligenceStreamError("invalid_stream_event")
      }
      return {
        type: value.type,
        occurred_at,
        data: {
          documents: requiredInteger(data, "documents", 0),
          embedding_units: requiredInteger(data, "embedding_units", 0),
          temporary: data.temporary,
        },
      }
    case "rag_retrieved":
      return {
        type: value.type,
        occurred_at,
        data: {
          retrieved_units: requiredInteger(data, "retrieved_units", 0),
          retrieval_limit: requiredInteger(data, "retrieval_limit", 1),
        },
      }
    case "report_generation_started":
      return {
        type: value.type,
        occurred_at,
        data: { company_name: requiredString(data, "company_name") },
      }
    case "analysis_completed":
      return {
        type: value.type,
        occurred_at,
        data: {
          company_name: requiredString(data, "company_name"),
          sector: requiredString(data, "sector"),
          report: requiredString(data, "report"),
        },
      }
    case "analysis_failed": {
      const code = data.code
      if (
        typeof code !== "string"
        || !(ANALYSIS_FAILURE_CODES as readonly string[]).includes(code)
      ) {
        throw new CompetitiveIntelligenceStreamError("invalid_stream_event")
      }
      return {
        type: value.type,
        occurred_at,
        data: { code: code as AnalysisFailureCode },
      }
    }
    default:
      throw new CompetitiveIntelligenceStreamError("invalid_stream_event")
  }
}

export async function consumeAnalysisStream(
  response: Response,
  onEvent: (event: AnalysisEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  if (!response.body) {
    throw new CompetitiveIntelligenceStreamError("stream_unavailable")
  }

  const contentType = response.headers.get("Content-Type")
  if (
    contentType !== null
    && contentType.split(";", 1)[0].trim().toLowerCase()
      !== "application/x-ndjson"
  ) {
    try {
      await response.body.cancel()
    } catch {
      // The protocol error remains authoritative if cancellation also fails.
    }
    throw new CompetitiveIntelligenceStreamError("invalid_stream_response")
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let terminalEvent: Extract<
    AnalysisEvent,
    { type: "analysis_completed" | "analysis_failed" }
  > | null = null
  let reachedEnd = false

  const processLine = (rawLine: string) => {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine
    if (!line.trim()) return
    if (terminalEvent !== null) {
      throw new CompetitiveIntelligenceStreamError("invalid_stream_event")
    }

    const event = parseAnalysisEvent(line)
    onEvent(event)
    if (event.type === "analysis_completed" || event.type === "analysis_failed") {
      terminalEvent = event
    }
  }

  try {
    while (true) {
      signal?.throwIfAborted()
      const { value, done } = await reader.read()
      signal?.throwIfAborted()
      buffer += decoder.decode(value, { stream: !done })

      const lines = buffer.split("\n")
      buffer = lines.pop() ?? ""
      lines.forEach(processLine)
      if (done) {
        reachedEnd = true
        break
      }
    }

    if (buffer.trim()) {
      processLine(buffer)
    }
    const terminal = terminalEvent as Extract<
      AnalysisEvent,
      { type: "analysis_completed" | "analysis_failed" }
    > | null
    if (terminal === null) {
      throw new CompetitiveIntelligenceStreamError("stream_ended_unexpectedly")
    }
    if (terminal.type === "analysis_failed") {
      throw new CompetitiveIntelligenceStreamError(terminal.data.code)
    }
  } catch (error) {
    if (!reachedEnd) {
      try {
        await reader.cancel()
      } catch {
        // The original stream or abort error remains authoritative.
      }
    }
    throw error
  } finally {
    reader.releaseLock()
  }
}
