from __future__ import annotations

from datetime import datetime
import os
from typing import Optional, List

from sqlalchemy import (
    create_engine,
    Integer,
    BigInteger,
    String,
    DateTime,
    Float,
    ForeignKey,
    UniqueConstraint,
    JSON,
    CheckConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from pathlib import Path


# --- SQLAlchemy Base/Engine/Session setup ---
_BASE_DIR = Path(__file__).resolve().parent
_DB_PATH = (_BASE_DIR / "database.sqlite").as_posix()
# Permite sobrescrever com DATABASE_URL (ex.: Postgres em produção)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_DB_PATH}")


class Base(DeclarativeBase):
    pass


engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,      # evita conexões mortas (ex.: timeouts do provider)
    pool_recycle=300         # recicla conexões a cada 5 minutos
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


# --- Models ---
class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # 'manager' | 'driver'

    # relationships
    assigned_routes: Mapped[List["Route"]] = relationship(
        back_populates="assigned_to", cascade="all, delete-orphan", passive_deletes=True
    )
    delivery_proofs: Mapped[List["DeliveryProof"]] = relationship(back_populates="driver")

    __table_args__ = (
        CheckConstraint("role in ('manager','driver')", name="ck_user_role"),
    )


class Route(Base):
    __tablename__ = "route"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    assigned_to_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # relationships
    assigned_to: Mapped[Optional[User]] = relationship(back_populates="assigned_routes")
    packages: Mapped[List["Package"]] = relationship(
        back_populates="route", cascade="all, delete-orphan", passive_deletes=True
    )


class Package(Base):
    __tablename__ = "package"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    route_id: Mapped[int] = mapped_column(Integer, ForeignKey("route.id", ondelete="CASCADE"), index=True)
    tracking_code: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    address: Mapped[Optional[str]] = mapped_column(String(500))
    neighborhood: Mapped[Optional[str]] = mapped_column(String(255))
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON)

    # relationships
    route: Mapped[Route] = relationship(back_populates="packages")
    proofs: Mapped[List["DeliveryProof"]] = relationship(
        back_populates="package", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("status in ('pending','delivered','failed')", name="ck_package_status"),
        UniqueConstraint("route_id", "tracking_code", name="uq_route_tracking"),
    )


class DeliveryProof(Base):
    __tablename__ = "delivery_proof"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    package_id: Mapped[int] = mapped_column(Integer, ForeignKey("package.id", ondelete="CASCADE"), index=True)
    driver_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    receiver_name: Mapped[str] = mapped_column(String(255))
    receiver_document: Mapped[str] = mapped_column(String(100))
    notes: Mapped[Optional[str]] = mapped_column(String(1000))
    photo1_path: Mapped[Optional[str]] = mapped_column(String(500))
    photo2_path: Mapped[Optional[str]] = mapped_column(String(500))
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)

    # relationships
    package: Mapped[Package] = relationship(back_populates="proofs")
    driver: Mapped[Optional[User]] = relationship(back_populates="delivery_proofs")


def init_db() -> None:
    """Create all tables if not exist."""
    Base.metadata.create_all(bind=engine)


def get_db_session():
    """Yield a database session (FastAPI dependency-style generator or manual context)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# If executed directly, initialize DB
if __name__ == "__main__":
    init_db()
    print("database initialized at:", DATABASE_URL)
