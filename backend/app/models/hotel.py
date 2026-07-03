"""Hotel model — stores real hotels independent of OTA platforms."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class Hotel(Base):
    __tablename__ = "hotels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    is_mine = Column(Boolean, default=False)
    distance_km = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    platform_mappings = relationship(
        "HotelPlatformMapping",
        back_populates="hotel",
        cascade="all, delete-orphan",
    )
    price_records = relationship("PriceRecord", back_populates="hotel")
    competitor_links = relationship(
        "HotelCompetitor",
        foreign_keys="HotelCompetitor.mine_hotel_id",
        back_populates="mine_hotel",
        cascade="all, delete-orphan",
    )
    competing_for_links = relationship(
        "HotelCompetitor",
        foreign_keys="HotelCompetitor.competitor_hotel_id",
        back_populates="competitor_hotel",
        cascade="all, delete-orphan",
    )

    @property
    def competitor_ids(self) -> list[int]:
        return [link.competitor_hotel_id for link in self.competitor_links]

    def __repr__(self):
        return f"<Hotel(id={self.id}, name='{self.name}', is_mine={self.is_mine})>"
