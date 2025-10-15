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
    Date,
    Text,
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
    phone: Mapped[Optional[str]] = mapped_column(String(20))  # Phone number of recipient
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


# --- Financial Models (Manager only) ---
class Expense(Base):
    """Registro de gastos da empresa"""
    __tablename__ = "expense"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # combustivel, salario, manutencao, outros
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    fuel_type: Mapped[Optional[str]] = mapped_column(String(50))  # gasolina, diesel, etanol (se type=combustivel)
    fuel_liters: Mapped[Optional[float]] = mapped_column(Float)
    employee_name: Mapped[Optional[str]] = mapped_column(String(255))  # se type=salario
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("user.telegram_user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("type in ('combustivel','salario','manutencao','outros')", name="ck_expense_type"),
    )


class Income(Base):
    """Registro de ganhos (receitas) da empresa"""
    __tablename__ = "income"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    route_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("route.id", ondelete="SET NULL"))
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("user.telegram_user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # relationships
    route: Mapped[Optional[Route]] = relationship()


class Mileage(Base):
    """Registro de quilometragem rodada"""
    __tablename__ = "mileage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    km_start: Mapped[float] = mapped_column(Float, nullable=False)
    km_end: Mapped[float] = mapped_column(Float, nullable=False)
    km_total: Mapped[float] = mapped_column(Float, nullable=False)  # calculado automaticamente
    notes: Mapped[Optional[str]] = mapped_column(String(500))
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("user.telegram_user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AIReport(Base):
    """Relatórios mensais gerados pelo Gemini AI"""
    __tablename__ = "ai_report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-12
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    report_text: Mapped[str] = mapped_column(Text, nullable=False)
    total_income: Mapped[float] = mapped_column(Float)
    total_expenses: Mapped[float] = mapped_column(Float)
    total_km: Mapped[float] = mapped_column(Float)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("user.telegram_user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("month", "year", name="uq_month_year"),
    )


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
