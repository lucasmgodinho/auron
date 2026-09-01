from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

CompanyName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=200),
]


class CompetitiveAnalysisRequest(BaseModel):
    company_name: CompanyName

    model_config = ConfigDict(extra="forbid")


class CompetitiveAnalysisResponse(BaseModel):
    company_name: str
    sector: str
    report: str
