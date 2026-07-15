from pydantic import BaseModel, Field

class StartRequest(BaseModel):
    yaml_content: str
    config: dict[str, object] = Field(default_factory=dict)

class StartProfileRequest(BaseModel):
    app_home: str = ""
    profile_uid: str
    config: dict[str, object] = Field(default_factory=dict)

class UpdateNodeRequest(BaseModel):
    name: str

class ExportRequest(BaseModel):
    node_ids: list[int]
    output_suffix: str = "_checked"

class RecheckRequest(BaseModel):
    config: dict[str, object] = Field(default_factory=dict)
