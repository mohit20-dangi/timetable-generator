from pydantic import BaseModel, Field, model_validator
from typing import Optional, Dict, List

DAY_NAMES = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


class AcademicYearBase(BaseModel):
    name: str
    num_sections: int = 1
    default_section_strength: int = 60
    # {"Mon": ["12:00", "13:00"], ...} - a day left out has no lunch break.
    lunch_windows: Dict[str, List[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate(self):
        if self.num_sections < 1:
            raise ValueError("num_sections must be at least 1")
        if self.default_section_strength < 1:
            raise ValueError("default_section_strength must be at least 1")
        for day, window in self.lunch_windows.items():
            if day not in DAY_NAMES:
                raise ValueError(f"'{day}' is not a valid day (use {sorted(DAY_NAMES)})")
            if len(window) != 2:
                raise ValueError(f"lunch_windows['{day}'] must be [start, end]")
            start, end = window
            if start >= end:
                raise ValueError(f"lunch_windows['{day}']: end time must be after start time")
        return self


class AcademicYearCreate(AcademicYearBase):
    id: str
    department_id: Optional[str] = None


class AcademicYearResponse(AcademicYearBase):
    id: str
    department_id: Optional[str] = None

    class Config:
        from_attributes = True
