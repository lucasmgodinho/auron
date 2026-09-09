type AnalysisRunState = {
  mounted: boolean
  aborted: boolean
  runId: number
  currentRunId: number
  organizationId: string
  currentOrganizationId: string | undefined
}

export function isAnalysisRunCurrent(state: AnalysisRunState): boolean {
  return state.mounted
    && !state.aborted
    && state.runId === state.currentRunId
    && state.organizationId === state.currentOrganizationId
}
