import { auronFetch } from '../../api/http'
import {
  consumeAnalysisStream,
  type AnalysisEvent,
  type CompetitiveAnalysis,
} from './stream-protocol'

export {
  ANALYSIS_FAILURE_CODES,
  CompetitiveIntelligenceStreamError,
  parseAnalysisEvent,
} from './stream-protocol'
export type {
  AnalysisEvent,
  AnalysisFailureCode,
  CompetitiveAnalysis,
} from './stream-protocol'

export class CompetitiveIntelligenceApiError extends Error {
  status: number
  detail: string | null

  constructor(message: string, status: number, detail: string | null) {
    super(message)
    this.name = "CompetitiveIntelligenceApiError"
    this.status = status
    this.detail = detail
  }
}

async function throwAnalysisApiError(response: Response): Promise<never> {
  let detail: string | null = null
  try {
    const payload = (await response.json()) as { detail?: unknown }
    if (typeof payload.detail === "string") detail = payload.detail
  } catch {
    detail = null
  }
  throw new CompetitiveIntelligenceApiError(
    "Competitive analysis failed",
    response.status,
    detail,
  )
}

export async function streamCompetitiveAnalysis(
  organizationId: string,
  companyName: string,
  onEvent: (event: AnalysisEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await auronFetch(
    `/organizations/${encodeURIComponent(organizationId)}`
      + "/modules/competitive-intelligence/analyses/stream",
    {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/x-ndjson",
      },
      body: JSON.stringify({ company_name: companyName }),
      signal,
    },
  )
  if (!response.ok) {
    await throwAnalysisApiError(response)
  }
  await consumeAnalysisStream(response, onEvent, signal)
}

export async function runCompetitiveAnalysis(
  organizationId: string,
  companyName: string,
): Promise<CompetitiveAnalysis> {
  const response = await auronFetch(
    `/organizations/${encodeURIComponent(organizationId)}/modules/competitive-intelligence/analyses`,
    {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ company_name: companyName }),
    },
  )
  if (!response.ok) {
    await throwAnalysisApiError(response)
  }
  return (await response.json()) as CompetitiveAnalysis
}
