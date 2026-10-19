from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db import Base


class GeneratedEntry(Base):
    """One scheduled session within a run. `alternative_rank` distinguishes
    the primary schedule (rank 1) from alternates (rank 2..N) generated in
    the same run for side-by-side comparison."""
    __tablename__ = "generated_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timetable_run_id = Column(Integer, ForeignKey("timetable_runs.id", ondelete="CASCADE"), nullable=False)
    alternative_rank = Column(Integer, default=1)
    # Shared by every period-row belonging to the same scheduled session
    # (a 2-period lab block is 2 rows with the same session_group). Lets an
    # edit move a whole block at once instead of one period at a time, and
    # lets exports merge the rows back into one visual cell.
    session_group = Column(String, nullable=True, index=True)
    day = Column(String, nullable=False)
    period = Column(Integer, nullable=False)
    # All five references below are SET NULL on delete rather than blocking
    # it: a historical (especially non-published) run must stay deletable-
    # from-under even after a subject/teacher/room/section/batch it used is
    # later removed from the live configuration - see Phase 0.2's cascade
    # table, which only *refuses* deletes that hit a *published* run.
    section_id = Column(String, ForeignKey("sections.id", ondelete="SET NULL"), nullable=True)
    batch_id = Column(String, ForeignKey("lab_batches.id", ondelete="SET NULL"), nullable=True)
    subject_id = Column(String, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True)
    teacher_id = Column(String, ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True)
    room_id = Column(String, ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True)
    # Every teacher beyond `teacher_id` assigned to this session, for a
    # subject with teachers_required > 1 (a lab needing two supervisors).
    # `teacher_id` stays the primary/first teacher so every older reader
    # keeps working; anything that reasons about teacher load or clashes
    # must use app/services/entry_teachers.py::entry_teacher_ids instead of
    # reading teacher_id alone. No FK: it is a list, and the same
    # SET NULL-on-delete leniency the columns above document applies -
    # a deleted teacher is pruned from the list by the teachers router.
    co_teacher_ids = Column(JSON, default=list)

    # is_locked: neither a manual edit nor an AI regeneration may move or
    # reassign this block. is_manual: placed or changed by hand (badge in UI).
    is_locked = Column(Boolean, default=False)
    is_manual = Column(Boolean, default=False)

    run = relationship("TimetableRun", backref="entries")
