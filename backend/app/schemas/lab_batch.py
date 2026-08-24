from pydantic import BaseModel

class LabBatchBase(BaseModel):
    batch_name: str
    strength: int = 30

class LabBatchCreate(LabBatchBase):
    id: str
    section_id: str

class LabBatchResponse(LabBatchBase):
    id: str
    section_id: str
    
    class Config:
        from_attributes = True