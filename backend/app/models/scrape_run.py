"""Scrape batch model."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trigger_type = Column(String, nullable=False, default="manual")
    status = Column(String, nullable=False, default="running")
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    total_tasks = Column(Integer, default=0)
    success_tasks = Column(Integer, default=0)
    failed_tasks = Column(Integer, default=0)
    error_summary = Column(Text, nullable=True)

    price_records = relationship("PriceRecord", back_populates="scrape_run")
    task_results = relationship("ScrapeTaskResult", back_populates="scrape_run")

    def __repr__(self):
        return f"<ScrapeRun(id={self.id}, status='{self.status}')>"
