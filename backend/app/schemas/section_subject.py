from pydantic import BaseModel
from typing import Optional

class SectionSubjectCreate(BaseModel):
    section_id: str
    subject_id: str
    is_elective: bool = False
    elective_group_id: Optional[str] = None