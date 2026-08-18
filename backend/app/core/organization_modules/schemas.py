from pydantic import BaseModel, ConfigDict, StrictBool


class ModuleResponse(BaseModel):
    key: str
    name_key: str


class OrganizationModuleResponse(ModuleResponse):
    enabled: bool


class OrganizationModuleUpdate(BaseModel):
    enabled: StrictBool

    model_config = ConfigDict(extra="forbid")
