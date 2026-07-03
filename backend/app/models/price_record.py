"""PriceRecord model — one row per (hotel, platform, check_in_date, scrape batch)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Date, Float, ForeignKey, Integer, String, Index
from sqlalchemy.orm import relationship

from app.database import Base


class PriceRecord(Base):
    __tablename__ = "price_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(Integer, ForeignKey("scrape_runs.id"), nullable=False)
    hotel_id = Column(Integer, ForeignKey("hotels.id"), nullable=False)
    platform = Column(String, nullable=False)
    check_in_date = Column(Date, nullable=False)
    cheapest_room = Column(String, nullable=True)
    cheapest_price = Column(Float, nullable=True)
    scraped_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    scrape_run = relationship("ScrapeRun", back_populates="price_records")
    hotel = relationship("Hotel", back_populates="price_records")

    __table_args__ = (
        Index("idx_price_batch", "batch_id"),
        Index("idx_price_hotel_platform_date_scraped", "hotel_id", "platform", "check_in_date", "scraped_at"),
        Index("idx_price_scraped_at", "scraped_at"),
    )

    def __repr__(self):
        return (
            f"<PriceRecord(hotel_id={self.hotel_id}, platform='{self.platform}', "
            f"check_in='{self.check_in_date}', price={self.cheapest_price})>"
        )
