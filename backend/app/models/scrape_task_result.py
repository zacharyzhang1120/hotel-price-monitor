"""Per hotel/platform scrape task result."""

from datetime import datetime
import json

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import relationship

from app.database import Base


class ScrapeTaskResult(Base):
    __tablename__ = "scrape_task_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(Integer, ForeignKey("scrape_runs.id"), nullable=False)
    hotel_id = Column(Integer, ForeignKey("hotels.id"), nullable=False)
    hotel_name = Column(String, nullable=False)
    platform = Column(String, nullable=False)
    status = Column(String, nullable=False)
    records_count = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    evidence_json = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=False)

    scrape_run = relationship("ScrapeRun", back_populates="task_results")
    hotel = relationship("Hotel")

    __table_args__ = (
        Index("idx_scrape_task_batch", "batch_id"),
        Index("idx_scrape_task_hotel_platform", "hotel_id", "platform"),
    )

    @property
    def evidence(self):
        if not self.evidence_json:
            return None
        try:
            return json.loads(self.evidence_json)
        except json.JSONDecodeError:
            return None

    @property
    def has_evidence(self) -> bool:
        return bool(self.evidence_json)
