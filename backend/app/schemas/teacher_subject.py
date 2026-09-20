from pydantic import BaseModel


class TeacherSubjectCreate(BaseModel):
    teacher_id: str
    subject_id: str
