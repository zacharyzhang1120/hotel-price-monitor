"""Database engine and session configuration."""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from app.config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """Dependency that provides a database session."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Create all tables. Call on app startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_sqlite_compat_columns(conn)


async def _ensure_sqlite_compat_columns(conn) -> None:
    """Add lightweight columns for existing SQLite databases."""
    if engine.url.get_backend_name() != "sqlite":
        return

    result = await conn.execute(text("PRAGMA table_info(scrape_task_results)"))
    columns = {row[1] for row in result.fetchall()}
    if "evidence_json" not in columns:
        await conn.execute(text("ALTER TABLE scrape_task_results ADD COLUMN evidence_json TEXT"))
