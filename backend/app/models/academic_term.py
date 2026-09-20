from sqlalchemy import Column, String, Date, Integer, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.db import Base


class AcademicTerm(Base):
    """A single semester's calendar. Separate from AcademicYear (which is
    the curriculum year-of-study, e.g. "3rd Year") - a term is a real
    calendar span with real holidays, and it's what turns a scheme's total
    contact hours into a weekly rate.

    working_days: list of day codes actually in session, e.g.
      ["Mon","Tue","Wed","Thu","Fri","Sat"]
    holidays: list of ISO date strings excluded from teaching_weeks.
    """
    __tablename__ = "academic_terms"

    id = Column(String, primary_key=True, index=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=False)
    name = Column(String, nullable=False)  # e.g. "2026-27 Odd Semester"
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    working_days = Column(JSON, default=lambda: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"])
    holidays = Column(JSON, default=list)

    department = relationship("Department", backref="terms")

    @property
    def teaching_weeks(self) -> int:
        """Whole weeks between start and end, minus weeks that are entirely
        holiday. Used to warn admins when a subject's weekly rate can't
        deliver its total scheme hours before the term ends."""
        total_days = (self.end_date - self.start_date).days + 1
        return max(1, total_days // 7)
