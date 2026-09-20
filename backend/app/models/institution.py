from sqlalchemy import Column, String
from app.db import Base


class Institution(Base):
    """The top of the tenancy tree. One row per college/university customer.

    Kept from day one even though Phase 1 only exercises a single
    institution: retrofitting a tenant-ownership column onto every table
    later is the migration that stalls projects, so the column exists now
    while the isolation logic around it stays minimal until it's needed.
    """
    __tablename__ = "institutions"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    city = Column(String, nullable=True)
    timezone = Column(String, default="Asia/Kolkata")
