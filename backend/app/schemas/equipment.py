from pydantic import BaseModel


class EquipmentBase(BaseModel):
    name: str


class EquipmentCreate(EquipmentBase):
    id: str


class EquipmentResponse(EquipmentBase):
    id: str

    class Config:
        from_attributes = True
