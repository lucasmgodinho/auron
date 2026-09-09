from collections.abc import Iterator
from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import StreamWriter

from .errors import (
    InvalidCompanyError,
    NoSearchResultsError,
    SearchProviderError,
)
from .question_generation import OpenAIQuestionGenerator
from .report_generation import OpenAIReportGenerator
from .schemas import AnalysisEvent, create_analysis_event
from .search import TavilySearchClient
from .vector_store import RETRIEVAL_LIMIT, ChromaContextStore


class CompetitiveAnalysisState(TypedDict, total=False):
    organization_id: str
    execution_id: str
    company_name: str
    sector: str
    questions: list[str]
    search_documents: list[dict[str, str]]
    context: str
    report: str


@dataclass(frozen=True, slots=True)
class CompetitiveAnalysisResult:
    company_name: str
    sector: str
    report: str


class CompetitiveIntelligenceWorkflow:
    def __init__(
        self,
        *,
        question_generator: OpenAIQuestionGenerator,
        search_client: TavilySearchClient,
        context_store: ChromaContextStore,
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
        self, *, organization_id: UUID, company_name: str
    ) -> CompetitiveAnalysisResult:
        result = self._graph.invoke(self._initial_state(organization_id, company_name))
        return CompetitiveAnalysisResult(
            company_name=result["company_name"],
            sector=result["sector"],
            report=result["report"],
        )

    def stream_analysis(
        self,
        *,
        organization_id: UUID,
        company_name: str,
    ) -> Iterator[AnalysisEvent]:
        for part in self._graph.stream(
            self._initial_state(organization_id, company_name),
            stream_mode="custom",
            version="v2",
        ):
            if not isinstance(part, dict) or part.get("type") != "custom":
                continue
            yield AnalysisEvent.model_validate(part.get("data"))

    @staticmethod
    def _initial_state(
        organization_id: UUID,
        company_name: str,
    ) -> CompetitiveAnalysisState:
        return CompetitiveAnalysisState(
            organization_id=str(organization_id),
            execution_id=str(uuid4()),
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
                {"sector": plan.sector, "questions": plan.questions},
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
        documents: list[dict[str, str]] = []
        questions = state["questions"]
        total = len(questions)
        failed_searches = 0

        for index, question in enumerate(questions, start=1):
            progress = {"question": question, "current": index, "total": total}
            writer(
                create_analysis_event("search_started", progress).model_dump(
                    mode="json"
                )
            )

            try:
                search_result = self._search_client.search(question)
            except SearchProviderError:
                failed_searches += 1
                writer(
                    create_analysis_event("search_failed", progress).model_dump(
                        mode="json"
                    )
                )
                continue

            answer_indexed = search_result.answer is not None
            writer(
                create_analysis_event(
                    "search_completed",
                    {
                        **progress,
                        "sources": [
                            {"title": source.title, "url": source.url}
                            for source in search_result.sources
                        ],
                        "answer_indexed": answer_indexed,
                    },
                ).model_dump(mode="json")
            )

            if answer_indexed:
                documents.append(
                    {"question": question, "answer": search_result.answer}
                )

        if total > 0 and failed_searches == total:
            raise SearchProviderError("All Tavily searches failed")
        if not documents:
            raise NoSearchResultsError("Tavily returned no valid answers")

        return CompetitiveAnalysisState(search_documents=documents)

    def _retrieve_context(
        self,
        state: CompetitiveAnalysisState,
        writer: StreamWriter,
    ) -> CompetitiveAnalysisState:
        retrieval_result = self._context_store.index_and_retrieve(
            organization_id=UUID(state["organization_id"]),
            execution_id=UUID(state["execution_id"]),
            company_name=state["company_name"],
            documents=state["search_documents"],
        )

        writer(
            create_analysis_event(
                "documents_indexed",
                {
                    "documents": retrieval_result.documents_indexed,
                    "embedding_units": retrieval_result.embedding_units_indexed,
                    "temporary": True,
                },
            ).model_dump(mode="json")
        )
        writer(
            create_analysis_event(
                "rag_retrieved",
                {
                    "retrieved_units": retrieval_result.embedding_units_retrieved,
                    "retrieval_limit": RETRIEVAL_LIMIT,
                },
            ).model_dump(mode="json")
        )

        return CompetitiveAnalysisState(
            context=retrieval_result.context,
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
