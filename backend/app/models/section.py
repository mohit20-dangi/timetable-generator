from pydantic import BaseModel
from typing import List, Optional


class SectionSubjectLink(BaseModel):
    subject_id: str
    is_elective: bool = False
    elective_group_id: Optional[str] = None


class LabBatch(BaseModel):
    id: str
    batch_name: str
    strength: int = 30


class SectionCreate(BaseModel):
    id: str
    year_id: str
    name: str
    strength: int = 60


class SectionResponse(SectionCreate):
    subjects: List[SectionSubjectLink] = []
    lab_batches: List[LabBatch] = []


class SectionSubjectAdd(BaseModel):
    subject_id: str
    is_elective: bool = False
    elective_group_id: Optional[str] = None


class LabBatchCreate(BaseModel):
    id: str
    batch_name: str
    strength: int = 30
