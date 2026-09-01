from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph

from .errors import InvalidCompanyError, NoSearchResultsError, SearchProviderError
from .question_generation import OpenAIQuestionGenerator
from .report_generation import OpenAIReportGenerator
from .search import TavilySearchClient
from .vector_store import ChromaContextStore


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
        result = self._graph.invoke(
            CompetitiveAnalysisState(
                organization_id=str(organization_id),
                execution_id=str(uuid4()),
                company_name=company_name,
            )
        )
        return CompetitiveAnalysisResult(
            company_name=result["company_name"],
            sector=result["sector"],
            report=result["report"],
        )

    def _generate_questions(
        self, state: CompetitiveAnalysisState
    ) -> CompetitiveAnalysisState:
        plan = self._question_generator.generate(state["company_name"])
        if not plan.is_valid_company:
            raise InvalidCompanyError("Company could not be validated")
        return CompetitiveAnalysisState(
            sector=plan.sector,
            questions=plan.questions,
        )

    def _search_web(
        self, state: CompetitiveAnalysisState
    ) -> CompetitiveAnalysisState:
        documents: list[dict[str, str]] = []
        provider_failed = False
        for question in state["questions"]:
            try:
                answer = self._search_client.search(question)
            except SearchProviderError:
                provider_failed = True
                continue
            if answer:
                documents.append({"question": question, "answer": answer})

        if not documents:
            if provider_failed:
                raise SearchProviderError("All Tavily searches failed")
            raise NoSearchResultsError("Tavily returned no valid answers")
        return CompetitiveAnalysisState(search_documents=documents)

    def _retrieve_context(
        self, state: CompetitiveAnalysisState
    ) -> CompetitiveAnalysisState:
        context = self._context_store.index_and_retrieve(
            organization_id=UUID(state["organization_id"]),
            execution_id=UUID(state["execution_id"]),
            company_name=state["company_name"],
            documents=state["search_documents"],
        )
        return CompetitiveAnalysisState(context=context)

    def _generate_report(
        self, state: CompetitiveAnalysisState
    ) -> CompetitiveAnalysisState:
        report = self._report_generator.generate(
            company_name=state["company_name"],
            sector=state["sector"],
            context=state["context"],
        )
        return CompetitiveAnalysisState(report=report)
