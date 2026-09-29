from pydantic import BaseModel
from typing import List, Optional


class SectionSubjectLink(BaseModel):
    subject_id: str
    is_elective: bool = False
    elective_group_id: Optional[str] = None
    # Only meaningful for lab subjects in a section that has lab batches defined.
    # False (default): each batch picks its own day/slot independently. True: every
    # batch must run this lab at the exact same slot (e.g. shared invigilation needs).
    batches_simultaneous: bool = False


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
    batches_simultaneous: bool = False


class LabBatchCreate(BaseModel):
    id: str
    batch_name: str
    strength: int = 30
