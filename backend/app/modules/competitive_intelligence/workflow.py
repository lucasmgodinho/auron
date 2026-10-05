from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import StreamWriter

from .document_processing import deduplicate_documents
from .errors import (
    InvalidCompanyError,
    NoSearchResultsError,
    SearchProviderError,
)
from .evidence import RetrievedEvidence, SourceDocument
from .question_generation import OpenAIQuestionGenerator
from .report_generation import OpenAIReportGenerator
from .schemas import AnalysisEvent, create_analysis_event
from .search import TavilySearchClient
from .vector_store import RETRIEVAL_LIMIT, ChromaEvidenceStore


class CompetitiveAnalysisState(TypedDict, total=False):
    organization_id: str
    execution_id: str
    company_name: str
    sector: str
    questions: list[str]
    search_documents: list[SourceDocument]
    documents_selected: int
    searches_executed: int
    context: str
    retrieved_evidence: tuple[RetrievedEvidence, ...]
    report: str


@dataclass(frozen=True, slots=True)
class CompetitiveAnalysisResult:
    company_name: str
    sector: str
    report: str
    evidence: tuple[RetrievedEvidence, ...] = ()


class CompetitiveIntelligenceWorkflow:
    def __init__(
        self,
        *,
        question_generator: OpenAIQuestionGenerator,
        search_client: TavilySearchClient,
        context_store: ChromaEvidenceStore,
        report_generator: OpenAIReportGenerator,
    ) -> None:
        self._question_generator = question_generator
        self._search_client = search_client
        self._context_store = context_store
        self._report_generator = report_generator

        graph = StateGraph(CompetitiveAnalysisState)
        graph.add_node("question_generation", self._generate_questions)
        graph.add_node("web_search", self._search_web)
        graph.add_node("context_retrieval", self._retrieve_context)
        graph.add_node("report_generation", self._generate_report)
        graph.add_edge(START, "question_generation")
        graph.add_edge("question_generation", "web_search")
        graph.add_edge("web_search", "context_retrieval")
        graph.add_edge("context_retrieval", "report_generation")
        graph.add_edge("report_generation", END)
        self._graph = graph.compile()

    def analyze(
        self,
        *,
        organization_id: UUID,
        company_name: str,
        run_id: UUID | None = None,
    ) -> CompetitiveAnalysisResult:
        result = self._graph.invoke(self._initial_state(organization_id, company_name, run_id))
        return CompetitiveAnalysisResult(
            company_name=result["company_name"],
            sector=result["sector"],
            report=result["report"],
            evidence=result["retrieved_evidence"],
        )

    def stream_analysis(
        self,
        *,
        organization_id: UUID,
        company_name: str,
        run_id: UUID | None = None,
        on_completed: Callable[[CompetitiveAnalysisResult], None] | None = None,
    ) -> Iterator[AnalysisEvent]:
        completion_event = None
        for part in self._graph.stream(
            self._initial_state(organization_id, company_name, run_id),
            stream_mode=["custom", "values"],
            version="v2",
        ):
            if not isinstance(part, dict):
                continue
            if part.get("type") == "custom":
                event = AnalysisEvent.model_validate(part.get("data"))
                if event.type == "analysis_completed":
                    completion_event = event
                else:
                    yield event
            elif part.get("type") == "values" and completion_event is not None:
                result = part["data"]
                if on_completed is not None:
                    on_completed(
                        CompetitiveAnalysisResult(
                            company_name=result["company_name"],
                            sector=result["sector"],
                            report=result["report"],
                            evidence=result["retrieved_evidence"],
                        )
                    )
                yield completion_event
                return

    @staticmethod
    def _initial_state(
        organization_id: UUID,
        company_name: str,
        run_id: UUID | None = None,
    ) -> CompetitiveAnalysisState:
        return CompetitiveAnalysisState(
            organization_id=str(organization_id),
            execution_id=str(run_id or uuid4()),
            company_name=company_name,
        )

    def _generate_questions(
        self,
        state: CompetitiveAnalysisState,
        writer: StreamWriter,
    ) -> CompetitiveAnalysisState:
        writer(
            create_analysis_event(
                "analysis_started",
                {"company_name": state["company_name"]},
            ).model_dump(mode="json")
        )
        plan = self._question_generator.generate(state["company_name"])
        if not plan.is_valid_company:
            raise InvalidCompanyError("Company could not be validated")

        writer(
            create_analysis_event(
                "questions_generated",
                {"sector": plan.sector, "questions": plan.questions, "count": len(plan.questions)},
            ).model_dump(mode="json")
        )

        return CompetitiveAnalysisState(
            sector=plan.sector,
            questions=plan.questions,
        )

    def _search_web(
        self,
        state: CompetitiveAnalysisState,
        writer: StreamWriter,
    ) -> CompetitiveAnalysisState:
        documents: list[SourceDocument] = []
        questions = state["questions"]
        total = len(questions)
        failed_searches = 0

        for index, question in enumerate(questions, start=1):
            progress = {"question": question, "current": index, "total": total}
            writer(create_analysis_event("search_started", progress).model_dump(mode="json"))

            try:
                search_result = self._search_client.search(question)
            except SearchProviderError:
                failed_searches += 1
                writer(create_analysis_event("search_failed", progress).model_dump(mode="json"))
                continue

            writer(
                create_analysis_event(
                    "search_completed",
                    {
                        **progress,
                        "sources": [
                            {"title": source.title, "url": source.url}
                            for source in search_result.sources
                        ],
                        "documents_selected": len(search_result.documents),
                    },
                ).model_dump(mode="json")
            )

            documents.extend(search_result.documents)

        if total > 0 and failed_searches == total:
            raise SearchProviderError("All Tavily searches failed")
        if not documents:
            raise NoSearchResultsError("Tavily returned no valid source documents")

        return CompetitiveAnalysisState(
            search_documents=deduplicate_documents(documents),
            documents_selected=len(documents),
            searches_executed=total,
        )

    def _retrieve_context(
        self,
        state: CompetitiveAnalysisState,
        writer: StreamWriter,
    ) -> CompetitiveAnalysisState:
        retrieval_result = self._context_store.index_and_retrieve(
            organization_id=UUID(state["organization_id"]),
            execution_id=UUID(state["execution_id"]),
            questions=state["questions"],
            documents=state["search_documents"],
        )

        writer(
            create_analysis_event(
                "documents_indexed",
                {
                    "documents": retrieval_result.documents_indexed,
                    "embedding_units": retrieval_result.embedding_units_indexed,
                    "temporary": True,
                    "searches_executed": state["searches_executed"],
                    "documents_selected": state["documents_selected"],
                    "unique_sources": len(state["search_documents"]),
                    "chunks_generated": retrieval_result.embedding_units_indexed,
                    "chunks_indexed": retrieval_result.embedding_units_indexed,
                },
            ).model_dump(mode="json")
        )
        writer(
            create_analysis_event(
                "rag_retrieved",
                {
                    "retrieved_units": retrieval_result.embedding_units_retrieved,
                    "retrieval_limit": RETRIEVAL_LIMIT * len(state["questions"]),
                    "top_k_per_query": RETRIEVAL_LIMIT,
                    "evidence_retrieved": retrieval_result.embedding_units_retrieved,
                },
            ).model_dump(mode="json")
        )

        return CompetitiveAnalysisState(
            context=retrieval_result.context,
            retrieved_evidence=retrieval_result.evidence,
        )

    def _generate_report(
        self,
        state: CompetitiveAnalysisState,
        writer: StreamWriter,
    ) -> CompetitiveAnalysisState:
        writer(
            create_analysis_event(
                "report_generation_started",
                {"company_name": state["company_name"]},
            ).model_dump(mode="json")
        )

        report = self._report_generator.generate(
            company_name=state["company_name"],
            sector=state["sector"],
            context=state["context"],
        )

        writer(
            create_analysis_event(
                "analysis_completed",
                {
                    "company_name": state["company_name"],
                    "sector": state["sector"],
                    "report": report,
                },
            ).model_dump(mode="json")
        )

        return CompetitiveAnalysisState(report=report)
