from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field

from .errors import ModelProviderError
from .telemetry import invoke_llm

MODEL_NAME = "gpt-4o-mini"
MAX_QUESTIONS = 40


class QuestionSuggestion(BaseModel):
    sector: str | None = None
    is_valid_company: bool
    questions: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class QuestionPlan(BaseModel):
    sector: str
    is_valid_company: bool
    questions: list[str]


class OpenAIQuestionGenerator:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None,
        model: str = MODEL_NAME,
        max_questions: int = MAX_QUESTIONS,
    ) -> None:
        self._max_questions = max_questions
        self._model_name = model
        self._model = ChatOpenAI(
            model=model,
            temperature=0,
            api_key=api_key,
            base_url=base_url,
        ).with_structured_output(QuestionSuggestion, method="json_schema")

    def generate(self, company_name: str) -> QuestionPlan:
        try:
            suggestion = invoke_llm(
                self._model,
                [
                    SystemMessage(
                        content=(
                            "Validate a company and prepare a competitive-analysis research plan. "
                            "Return only the requested structured output."
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"Company: {company_name}\n"
                            "Determine whether this is a known real company, identify its primary "
                            "sector, and generate targeted questions covering competitors, market "
                            "share, products, pricing, technology, supply chain, strengths, "
                            "weaknesses, differentiators, trends, regulation, growth "
                            "opportunities, "
                            "and actionable competitive strategy. "
                            f"Generate no more than {self._max_questions} questions."
                        )
                    ),
                ],
                "question_generation",
                model_name=getattr(self, "_model_name", MODEL_NAME),
            )
        except Exception as error:
            raise ModelProviderError("Question generation failed") from error

        if not isinstance(suggestion, QuestionSuggestion):
            raise ModelProviderError("Question generation returned an invalid result")

        questions = [
            question.strip()
            for question in suggestion.questions[: self._max_questions]
            if question.strip()
        ]
        sector = (suggestion.sector or "").strip()
        if suggestion.is_valid_company and (not sector or not questions):
            raise ModelProviderError("Question generation returned an incomplete result")
        return QuestionPlan(
            sector=sector,
            is_valid_company=suggestion.is_valid_company,
            questions=questions,
        )
