import { useTranslation } from "react-i18next"

import type { AnalysisEvent } from "./api"

type AnalysisActivityProps = {
  events: AnalysisEvent[]
  isAnalyzing: boolean
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

function eventKey(event: AnalysisEvent, index: number): string {
  const progress = "current" in event.data ? `-${event.data.current}` : ""
  return `${event.occurred_at}-${event.type}${progress}-${index}`
}

export function AnalysisActivity({
  events,
  isAnalyzing,
}: AnalysisActivityProps) {
  const { t, i18n } = useTranslation()
  const headingId = "competitive-analysis-activity-heading"
  const timeFormatter = new Intl.DateTimeFormat(i18n.language, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })

  return (
    <section className="analysis-activity" aria-labelledby={headingId}>
      <h3 id={headingId}>{t("competitive_intelligence.activity.title")}</h3>
      <ol
        role="log"
        aria-labelledby={headingId}
        aria-live="polite"
        aria-relevant="additions"
        aria-atomic="false"
        aria-busy={isAnalyzing}
      >
        {events.map((event, index) => (
          <li key={eventKey(event, index)}>
            <time dateTime={event.occurred_at}>
              {timeFormatter.format(new Date(event.occurred_at))}
            </time>
            <div className="analysis-activity-content">
              <AnalysisEventContent event={event} />
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}

function AnalysisEventContent({ event }: { event: AnalysisEvent }) {
  const { t } = useTranslation()

  switch (event.type) {
    case "analysis_started":
      return <p>{t("competitive_intelligence.activity.started", {
        company: event.data.company_name,
      })}</p>

    case "questions_generated":
      return (
        <details>
          <summary>{t("competitive_intelligence.activity.questions", {
            count: event.data.questions.length,
            sector: event.data.sector,
          })}</summary>
          <ul>
            {event.data.questions.map((question, index) => (
              <li key={`${index}-${question}`}>{question}</li>
            ))}
          </ul>
        </details>
      )

    case "search_started":
      return (
        <>
          <p>{t("competitive_intelligence.activity.searching", {
            current: event.data.current,
            total: event.data.total,
          })}</p>
          <p className="analysis-activity-detail">{event.data.question}</p>
        </>
      )

    case "search_completed": {
      const safeSources = event.data.sources.filter((source) => (
        isSafeHttpUrl(source.url)
      ))
      return (
        <details>
          <summary>{t("competitive_intelligence.activity.searchCompleted", {
            current: event.data.current,
            total: event.data.total,
            count: safeSources.length,
          })}</summary>
          <p className="analysis-activity-detail">{event.data.question}</p>
          <p className="analysis-activity-detail">
            {t(event.data.documents_selected > 0
              ? "competitive_intelligence.activity.documentsSelected"
              : "competitive_intelligence.activity.noDocumentsSelected")}
          </p>
          {safeSources.length > 0 ? (
            <ul className="analysis-source-list">
              {safeSources.map((source) => (
                <li key={source.url}>
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {source.title}
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="analysis-activity-detail">
              {t("competitive_intelligence.activity.noSources")}
            </p>
          )}
        </details>
      )
    }

    case "search_failed":
      return (
        <>
          <p>{t("competitive_intelligence.activity.searchFailed", {
            current: event.data.current,
            total: event.data.total,
          })}</p>
          <p className="analysis-activity-detail">{event.data.question}</p>
        </>
      )

    case "documents_indexed":
      return <p>{t("competitive_intelligence.activity.documents", {
        documents: event.data.documents,
        units: event.data.embedding_units,
      })}</p>

    case "rag_retrieved":
      return <p>{t("competitive_intelligence.activity.rag", {
        count: event.data.retrieved_units,
        limit: event.data.retrieval_limit,
      })}</p>

    case "report_generation_started":
      return <p>{t("competitive_intelligence.activity.report", {
        company: event.data.company_name,
      })}</p>

    case "analysis_completed":
      return <p>{t("competitive_intelligence.activity.completed")}</p>

    case "analysis_failed":
      return <p>{t("competitive_intelligence.activity.failed")}</p>
  }
}
