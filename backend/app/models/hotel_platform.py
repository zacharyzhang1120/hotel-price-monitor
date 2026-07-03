"""Platform-specific hotel mapping."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class HotelPlatformMapping(Base):
    __tablename__ = "hotel_platform_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hotel_id = Column(Integer, ForeignKey("hotels.id"), nullable=False)
    platform = Column(String, nullable=False)
    platform_hotel_id = Column(String, nullable=False)
    hotel_url = Column(String, nullable=True)
    default_room_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    hotel = relationship("Hotel", back_populates="platform_mappings")

    __table_args__ = (
        UniqueConstraint("platform", "platform_hotel_id", name="uq_platform_hotel"),
    )

    def __repr__(self):
        return (
            f"<HotelPlatformMapping(hotel_id={self.hotel_id}, "
            f"platform='{self.platform}', platform_hotel_id='{self.platform_hotel_id}')>"
        )
