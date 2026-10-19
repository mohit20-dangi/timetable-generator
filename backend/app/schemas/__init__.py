from app.schemas.department import DepartmentCreate, DepartmentResponse, DepartmentUpdate
from app.schemas.academic_term import AcademicTermCreate, AcademicTermResponse
from app.schemas.academic_year import AcademicYearCreate, AcademicYearResponse
from app.schemas.section import SectionCreate, SectionResponse
from app.schemas.lab_batch import LabBatchCreate, LabBatchResponse
from app.schemas.elective_group import (
    ElectiveGroupCreate, ElectiveGroupResponse,
    ElectivePreflightResponse, ElectivePreflightIssue,
)
from app.schemas.lab_rotation_group import (
    LabRotationGroupCreate, LabRotationGroupResponse,
    LabRotationPreflightResponse, LabRotationPreflightIssue,
)
from app.schemas.subject import SubjectCreate, SubjectResponse
from app.schemas.batch_preflight import BatchPreflightResponse, BatchPreflightIssue
from app.schemas.subject_type import SubjectTypeCreate, SubjectTypeResponse
from app.schemas.equipment import EquipmentCreate, EquipmentResponse
from app.schemas.teacher import TeacherCreate, TeacherResponse
from app.schemas.teacher_subject import TeacherSubjectCreate
from app.schemas.room import RoomCreate, RoomResponse
from app.schemas.time_slot import (
    TimeSlotCreate, TimeSlotResponse, TimeSlotUpdate, BellSchedulePeriod, BellScheduleReplace,
)
from app.schemas.prerequisite import PrerequisiteCreate
from app.schemas.constraint_rule import ConstraintRuleCreate, ConstraintRuleResponse
from app.schemas.constraint_profile import ConstraintProfileCreate, ConstraintProfileResponse
from app.schemas.user import UserCreate, UserResponse, LoginRequest, TokenResponse
from app.schemas.nl_constraint import NLConstraintParseRequest, NLConstraintParseResponse
from app.schemas.nl_edit import NLMoveParseRequest, NLMoveParseResponse
from app.schemas.timetable_ai import (
    TimetableAIPlanRequest, TimetableAIAction, TimetableAIPlanResponse, TimetableAIApplyRequest,
)
from app.schemas.timetable import (
    TimetableGenerateRequest, TimetableRunResponse, EntryIdentifier,
    EditEntryRequest, ConflictDetail, SuggestedSlot, EditEntryResponse,
    PublishRequest, TimetableEntryResponse, ValidationIssue, ValidationResponse,
    AlternativeSummary, AlternativesResponse, AlternativeDetailResponse,
)

# Backward-compat alias: the old constraints router imports SectionSubjectCreate
# from app.schemas even though there's no dedicated model concept beyond the
# raw ids + flags already on the SectionSubject table.
from pydantic import BaseModel
from typing import Optional


class SectionSubjectCreate(BaseModel):
    section_id: str
    subject_id: str
    is_elective: bool = False
    elective_group_id: Optional[str] = None
    attends_with_section_id: Optional[str] = None
    attends_with_batch_id: Optional[str] = None


__all__ = [

    "DepartmentCreate", "DepartmentResponse", "DepartmentUpdate",
    "AcademicTermCreate", "AcademicTermResponse",
    "AcademicYearCreate", "AcademicYearResponse",
    "SectionCreate", "SectionResponse",
    "LabBatchCreate", "LabBatchResponse",
    "ElectiveGroupCreate", "ElectiveGroupResponse",
    "ElectivePreflightResponse", "ElectivePreflightIssue",
    "LabRotationGroupCreate", "LabRotationGroupResponse",
    "LabRotationPreflightResponse", "LabRotationPreflightIssue",
    "SubjectCreate", "SubjectResponse",
    "BatchPreflightResponse", "BatchPreflightIssue",
    "SubjectTypeCreate", "SubjectTypeResponse",
    "EquipmentCreate", "EquipmentResponse",
    "TeacherCreate", "TeacherResponse",
    "TeacherSubjectCreate",
    "RoomCreate", "RoomResponse",
    "TimeSlotCreate", "TimeSlotResponse",
    "PrerequisiteCreate",
    "ConstraintRuleCreate", "ConstraintRuleResponse",
    "ConstraintProfileCreate", "ConstraintProfileResponse",
    "UserCreate", "UserResponse", "LoginRequest", "TokenResponse",
    "NLConstraintParseRequest", "NLConstraintParseResponse",
    "NLMoveParseRequest", "NLMoveParseResponse",
    "TimetableAIPlanRequest", "TimetableAIAction", "TimetableAIPlanResponse", "TimetableAIApplyRequest",
    "TimetableGenerateRequest", "TimetableRunResponse", "EntryIdentifier",
    "EditEntryRequest", "ConflictDetail", "SuggestedSlot", "EditEntryResponse",
    "PublishRequest", "TimetableEntryResponse", "ValidationIssue", "ValidationResponse",
    "AlternativeSummary", "AlternativesResponse", "AlternativeDetailResponse",
    "SectionSubjectCreate",
]
