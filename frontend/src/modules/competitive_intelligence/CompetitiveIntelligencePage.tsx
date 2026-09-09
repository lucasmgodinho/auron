import { type FormEvent, useCallback, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import ReactMarkdown from "react-markdown"
import { Link, useParams } from "react-router-dom"

import {
  AccessControlApiError,
  getOrganizationAccessSummary,
} from "../../api/access-control"
import { getOrganization, OrganizationApiError, type Organization } from "../../api/organizations"
import { getPlatformAdminStatus } from "../../api/platform-admin"
import { useAuth } from "../../auth/useAuth"
import { AppShell } from "../../components/AppShell"
import { LoadingState } from "../../components/LoadingState"
import { usePageMetadata } from "../../hooks/usePageMetadata"
import {
  CompetitiveIntelligenceApiError,
  CompetitiveIntelligenceStreamError,
  streamCompetitiveAnalysis,
  type AnalysisEvent,
  type CompetitiveAnalysis,
} from "./api"

import { AnalysisActivity } from "./AnalysisActivity"
import { isAnalysisRunCurrent } from "./analysis-run"

const MODULE_KEY = "competitive_intelligence"
const RUN_PERMISSION = "competitive_intelligence.analysis.run"

type PageStatus = "loading" | "ready" | "forbidden" | "not-found" | "error"

function getAnalysisErrorKey(
  error: unknown,
): string {
  if (
    error
    instanceof CompetitiveIntelligenceStreamError
  ) {
    switch (error.code) {
      case "invalid_company":
        return "competitive_intelligence.errors.invalidCompany"

      case "no_search_results":
        return "competitive_intelligence.errors.noResults"

      case "search_provider_failed":
        return "competitive_intelligence.errors.search"

      case "model_provider_failed":
        return "competitive_intelligence.errors.model"

      case "vector_store_failed":
        return "competitive_intelligence.errors.context"

      case "stream_ended_unexpectedly":
      case "stream_unavailable":
      case "invalid_stream_event":
      case "invalid_stream_response":
        return "competitive_intelligence.errors.connection"

      default:
        return "competitive_intelligence.errors.unexpected"
    }
  }
  if (!(error instanceof CompetitiveIntelligenceApiError)) {
    return "competitive_intelligence.errors.unexpected"
  }
  if (error.status === 422 && error.detail === "Company could not be validated") {
    return "competitive_intelligence.errors.invalidCompany"
  }
  if (
    error.status === 422
    && error.detail === "No valid search results were found"
  ) {
    return "competitive_intelligence.errors.noResults"
  }
  if (error.status === 502 && error.detail === "Competitive search provider failed") {
    return "competitive_intelligence.errors.search"
  }
  if (error.status === 502 && error.detail === "Competitive analysis model failed") {
    return "competitive_intelligence.errors.model"
  }
  if (error.status === 503) {
    return "competitive_intelligence.errors.configuration"
  }
  return "competitive_intelligence.errors.unexpected"
}

export function CompetitiveIntelligencePage() {
  const { t } = useTranslation()
  const { organizationId } = useParams<{ organizationId: string }>()
  const { user, logout, refreshUser } = useAuth()
  const requestId = useRef(0)
  const analysisRunId = useRef(0)
  const isMounted = useRef(true)
  const currentOrganizationId = useRef(organizationId)
  currentOrganizationId.current = organizationId
  const [pageStatus, setPageStatus] = useState<PageStatus>("loading")
  const [organization, setOrganization] = useState<Organization | null>(null)
  const [companyName, setCompanyName] = useState("")
  const [analysis, setAnalysis] = useState<CompetitiveAnalysis | null>(null)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [isPlatformAdmin, setIsPlatformAdmin] = useState(false)
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)
  const [analysisEvents, setAnalysisEvents] = useState<AnalysisEvent[]>([])
  const analysisAbortController = useRef<AbortController | null>(null)

  usePageMetadata(
    t("competitive_intelligence.meta.title"),
    t("competitive_intelligence.meta.description"),
  )

  const loadPage = useCallback(async () => {
    const currentRequestId = ++requestId.current
    setPageStatus("loading")
    setOrganization(null)
    if (!organizationId) {
      setPageStatus("not-found")
      return
    }
    try {
      const [nextOrganization, access] = await Promise.all([
        getOrganization(organizationId),
        getOrganizationAccessSummary(organizationId),
      ])
      if (requestId.current !== currentRequestId) return
      const canRun = access.enabled_modules.includes(MODULE_KEY)
        && (access.is_owner || access.permissions.includes(RUN_PERMISSION))
      if (!canRun) {
        setPageStatus("forbidden")
        return
      }
      setOrganization(nextOrganization)
      setPageStatus("ready")
    } catch (error) {
      if (requestId.current !== currentRequestId) return
      const status = error instanceof OrganizationApiError
        || error instanceof AccessControlApiError
        ? error.status
        : null
      if (status === 401) {
        await refreshUser()
        if (requestId.current === currentRequestId) setPageStatus("error")
      } else if (status === 403) {
        setPageStatus("forbidden")
      } else if (status === 404 || status === 422) {
        setPageStatus("not-found")
      } else {
        setPageStatus("error")
      }
    }
  }, [organizationId, refreshUser])

  useEffect(() => {
    isMounted.current = true
    return () => {
      isMounted.current = false
      analysisRunId.current += 1
      analysisAbortController.current?.abort()
    }
  }, [])

  useEffect(() => {
    analysisRunId.current += 1
    analysisAbortController.current?.abort()
    analysisAbortController.current = null
    setIsAnalyzing(false)
    setAnalysis(null)
    setAnalysisEvents([])
    setAnalysisError(null)
  }, [organizationId])

  useEffect(() => {
    void loadPage()
    return () => { requestId.current += 1 }
  }, [loadPage])

  useEffect(() => {
    let active = true
    void getPlatformAdminStatus()
      .then((hasAccess) => { if (active) setIsPlatformAdmin(hasAccess) })
      .catch(() => { if (active) setIsPlatformAdmin(false) })
    return () => { active = false }
  }, [])

  async function handleLogout() {
    setIsLoggingOut(true)
    setLogoutError(null)
    try {
      await logout()
    } catch {
      setLogoutError(t("common.account.logoutError"))
      setIsLoggingOut(false)
    }
  }

  async function handleSubmit(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    if (!organizationId || isAnalyzing) return

    const normalizedCompanyName = companyName.trim()

    if (normalizedCompanyName.length < 2) {
      setAnalysisError(
        t("competitive_intelligence.errors.input"),
      )
      return
    }

    analysisAbortController.current?.abort()
    const controller = new AbortController()
    const runId = ++analysisRunId.current
    const runOrganizationId = organizationId
    analysisAbortController.current = controller
    const isCurrentRun = () => isAnalysisRunCurrent({
      mounted: isMounted.current,
      aborted: controller.signal.aborted,
      runId,
      currentRunId: analysisRunId.current,
      organizationId: runOrganizationId,
      currentOrganizationId: currentOrganizationId.current,
    })

    setIsAnalyzing(true)
    setAnalysis(null)
    setAnalysisEvents([])
    setAnalysisError(null)

    try {
      await streamCompetitiveAnalysis(
        organizationId,
        normalizedCompanyName,
        (analysisEvent) => {
          if (!isCurrentRun()) {
            return
          }
          setAnalysisEvents((currentEvents) => [
            ...currentEvents,
            analysisEvent,
          ])

          if (
            analysisEvent.type
            === "analysis_completed"
          ) {
            setAnalysis(analysisEvent.data)
            setCompanyName(
              analysisEvent.data.company_name,
            )
          }
        },
        controller.signal,
      )
      if (!isCurrentRun()) {
        return
      }
    } catch (error) {
      if (
        !isCurrentRun()
        || (error instanceof DOMException && error.name === "AbortError")
      ) {
        return
      }

      if (
        error instanceof CompetitiveIntelligenceApiError
        && error.status === 401
      ) {
        await refreshUser()
        if (!isCurrentRun()) {
          return
        }
      }

      setAnalysisError(
        t(getAnalysisErrorKey(error)),
      )
    } finally {
      if (
        isCurrentRun()
        && analysisAbortController.current === controller
      ) {
        analysisAbortController.current = null
        setIsAnalyzing(false)
      }
    }
  }

  if (user === null) return null

  const modulePath = organizationId
    ? `/app/organizations/${organizationId}/modules/competitive-intelligence`
    : undefined

  if (pageStatus === "loading") {
    return (
      <AppShell
        user={user}
        isLoggingOut={isLoggingOut}
        logoutError={logoutError}
        onLogout={() => void handleLogout()}
        isPlatformAdmin={isPlatformAdmin}
        activePage="competitiveIntelligence"
        competitiveIntelligencePath={modulePath}
      >
        <LoadingState label={t("common.status.loadingContent")} />
      </AppShell>
    )
  }

  if (pageStatus !== "ready" || organization === null) {
    const copy = pageStatus === "forbidden"
      ? {
        eyebrow: t("competitive_intelligence.access.deniedEyebrow"),
        heading: t("competitive_intelligence.access.deniedTitle"),
        body: t("competitive_intelligence.access.deniedBody"),
      }
      : pageStatus === "not-found"
        ? {
          eyebrow: t("organizations.home.notFoundEyebrow"),
          heading: t("organizations.home.notFoundTitle"),
          body: t("organizations.home.notFoundBody"),
        }
        : {
          eyebrow: t("competitive_intelligence.access.errorEyebrow"),
          heading: t("competitive_intelligence.access.errorTitle"),
          body: t("competitive_intelligence.access.errorBody"),
        }
    return (
      <AppShell
        user={user}
        isLoggingOut={isLoggingOut}
        logoutError={logoutError}
        onLogout={() => void handleLogout()}
        isPlatformAdmin={isPlatformAdmin}
        activePage="competitiveIntelligence"
        competitiveIntelligencePath={modulePath}
      >
        <section className="status-card content-status-card">
          <p className="eyebrow">{copy.eyebrow}</p>
          <h1>{copy.heading}</h1>
          <p>{copy.body}</p>
          {pageStatus === "error" ? (
            <button
              className="button button-primary"
              type="button"
              onClick={() => void loadPage()}
            >
              {t("common.actions.retry")}
            </button>
          ) : (
            <Link className="button button-primary status-link" to="/app">
              {t("organizations.home.return")}
            </Link>
          )}
        </section>
      </AppShell>
    )
  }

  return (
    <AppShell
      user={user}
      isLoggingOut={isLoggingOut}
      logoutError={logoutError}
      onLogout={() => void handleLogout()}
      isPlatformAdmin={isPlatformAdmin}
      activePage="competitiveIntelligence"
      organizationName={organization.name}
      competitiveIntelligencePath={modulePath}
    >
      <header className="page-header organization-page-header">
        <p className="eyebrow">{t("competitive_intelligence.page.eyebrow")}</p>
        <h1>{t("competitive_intelligence.page.title")}</h1>
        <p>{t("competitive_intelligence.page.description")}</p>
      </header>

      <section className="form-card competitive-intelligence-form" aria-labelledby="analysis-form-heading">
        <div>
          <p className="eyebrow">{organization.name}</p>
          <h2 id="analysis-form-heading">{t("competitive_intelligence.form.title")}</h2>
          <p>{t("competitive_intelligence.form.description")}</p>
        </div>
        <form onSubmit={(event) => void handleSubmit(event)} aria-busy={isAnalyzing}>
          <label className="field-label" htmlFor="competitive-company-name">
            {t("competitive_intelligence.form.company")}
          </label>
          <div className="competitive-intelligence-search">
            <input
              id="competitive-company-name"
              className="text-input"
              value={companyName}
              onChange={(event) => setCompanyName(event.target.value)}
              maxLength={200}
              disabled={isAnalyzing}
              required
            />
            <button
              className="button button-primary"
              type="submit"
              disabled={isAnalyzing}
            >
              {isAnalyzing
                ? t("competitive_intelligence.form.searching")
                : t("competitive_intelligence.form.submit")}
            </button>
          </div>
        </form>
        {analysisEvents.length > 0 ? (
          <AnalysisActivity
            events={analysisEvents}
            isAnalyzing={isAnalyzing}
          />
        ) : null}
        {analysisError ? (
          <div className="alert alert-danger" role="alert">{analysisError}</div>
        ) : null}
      </section>

      {analysis ? (
        <article className="competitive-intelligence-report" aria-labelledby="competitive-report-heading">
          <header>
            <p className="eyebrow">{t("competitive_intelligence.report.eyebrow")}</p>
            <h2 id="competitive-report-heading">{analysis.company_name}</h2>
            <p>
              {t("competitive_intelligence.report.sector", {
                sector: analysis.sector,
              })}
            </p>
          </header>
          <div className="markdown-content">
            <ReactMarkdown skipHtml>{analysis.report}</ReactMarkdown>
          </div>
        </article>
      ) : null}
    </AppShell>
  )
}
