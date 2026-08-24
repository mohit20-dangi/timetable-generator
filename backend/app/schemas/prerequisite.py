from pydantic import BaseModel

class PrerequisiteCreate(BaseModel):
    subject_id: str
    requires_subject_id: str