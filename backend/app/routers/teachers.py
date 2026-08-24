from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db import get_db
from app.models import Teacher, TeacherSubject
from app.schemas import TeacherCreate, TeacherResponse, TeacherSubjectCreate

router = APIRouter(prefix="/api/teachers", tags=["Teachers"])

@router.post("/", response_model=TeacherResponse)
def create_teacher(teacher: TeacherCreate, db: Session = Depends(get_db)):
    # Extract subjects list before creating teacher
    teacher_data = teacher.model_dump()
    subjects = teacher_data.pop("subjects", [])
    
    db_teacher = Teacher(**teacher_data)
    db.add(db_teacher)
    db.commit()
    db.refresh(db_teacher)
    
    # Add teacher-subject relationships
    for subject_id in subjects:
        ts = TeacherSubject(teacher_id=db_teacher.id, subject_id=subject_id)
        db.add(ts)
    db.commit()
    
    return db_teacher

@router.get("/", response_model=List[TeacherResponse])
def list_teachers(db: Session = Depends(get_db)):
    return db.query(Teacher).all()

@router.get("/{teacher_id}", response_model=TeacherResponse)
def get_teacher(teacher_id: str, db: Session = Depends(get_db)):
    teacher = db.query(Teacher).filter(Teacher.id == teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")
    return teacher

@router.post("/{teacher_id}/subjects")
def add_teacher_subject(teacher_id: str, ts: TeacherSubjectCreate, db: Session = Depends(get_db)):
    teacher = db.query(Teacher).filter(Teacher.id == teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")
    
    db_ts = TeacherSubject(teacher_id=teacher_id, subject_id=ts.subject_id)
    db.add(db_ts)
    db.commit()
    return {"message": "Subject added to teacher"}

@router.delete("/{teacher_id}/subjects/{subject_id}")
def remove_teacher_subject(teacher_id: str, subject_id: str, db: Session = Depends(get_db)):
    ts = db.query(TeacherSubject).filter(
        TeacherSubject.teacher_id == teacher_id,
        TeacherSubject.subject_id == subject_id
    ).first()
    if not ts:
        raise HTTPException(status_code=404, detail="Teacher-Subject mapping not found")
    db.delete(ts)
    db.commit()
    return {"message": "Subject removed from teacher"}

@router.delete("/{teacher_id}")
def delete_teacher(teacher_id: str, db: Session = Depends(get_db)):
    teacher = db.query(Teacher).filter(Teacher.id == teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")
    db.delete(teacher)
    db.commit()
    return {"message": "Teacher deleted"}