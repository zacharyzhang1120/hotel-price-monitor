"""Relationship between one owned hotel and its competitors."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class HotelCompetitor(Base):
    __tablename__ = "hotel_competitors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mine_hotel_id = Column(Integer, ForeignKey("hotels.id"), nullable=False)
    competitor_hotel_id = Column(Integer, ForeignKey("hotels.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    mine_hotel = relationship(
        "Hotel",
        foreign_keys=[mine_hotel_id],
        back_populates="competitor_links",
    )
    competitor_hotel = relationship(
        "Hotel",
        foreign_keys=[competitor_hotel_id],
        back_populates="competing_for_links",
    )

    __table_args__ = (
        UniqueConstraint("mine_hotel_id", "competitor_hotel_id", name="uq_mine_competitor"),
    )
