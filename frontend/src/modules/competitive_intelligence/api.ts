export type CompetitiveAnalysis = {
  company_name: string
  sector: string
  report: string
}

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
  return (await response.json()) as CompetitiveAnalysis
}
import { auronFetch } from '../../api/http'
