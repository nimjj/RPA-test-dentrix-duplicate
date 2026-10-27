from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organization"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    trusted_ips: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of IPs / CIDRs

    locations: Mapped[list["Location"]] = relationship(back_populates="org", order_by="Location.id")


class Location(Base):
    __tablename__ = "location"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organization.id"))
    name: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(8))
    lock_before_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    org: Mapped[Organization] = relationship(back_populates="locations")
    payment_types: Mapped[list["PaymentType"]] = relationship(
        back_populates="location", order_by="PaymentType.sort"
    )


class PaymentType(Base):
    __tablename__ = "payment_type"

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"))
    code: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(60))
    sort: Mapped[int] = mapped_column(Integer, default=0)

    location: Mapped[Location] = relationship(back_populates="payment_types")


class User(Base):
    __tablename__ = "user"
    __table_args__ = (UniqueConstraint("org_id", "username"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organization.id"))
    username: Mapped[str] = mapped_column(String(60))
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(30))
    password_hash: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20))  # admin | front_desk | automation
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | blocked
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    lock_stage: Mapped[int] = mapped_column(Integer, default=0)  # 0 none yet, 1 had the 5-minute lock
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False)  # bot detection flag

    org: Mapped[Organization] = relationship()
    locations: Mapped[list[Location]] = relationship(secondary="user_location", order_by="Location.id")


class UserLocation(Base):
    __tablename__ = "user_location"

    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"), primary_key=True)


class Device(Base):
    __tablename__ = "device"
    __table_args__ = (UniqueConstraint("user_id", "token_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime)


class SessionRow(Base):
    __tablename__ = "session"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of the cookie token
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    location_id: Mapped[Optional[int]] = mapped_column(ForeignKey("location.id"), nullable=True)
    state: Mapped[str] = mapped_column(String(30))  # pending_mfa_email | pending_mfa_sms | active
    created_at: Mapped[datetime] = mapped_column(DateTime)
    last_activity: Mapped[datetime] = mapped_column(DateTime)
    ended_reason: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ip: Mapped[str] = mapped_column(String(64), default="")

    user: Mapped[User] = relationship()


class MfaChallenge(Base):
    __tablename__ = "mfa_challenge"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("session.id"))
    step: Mapped[str] = mapped_column(String(10))  # email | sms
    code_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class SmsMessage(Base):
    __tablename__ = "sms_message"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    username: Mapped[str] = mapped_column(String(60))
    phone: Mapped[str] = mapped_column(String(30))
    code: Mapped[str] = mapped_column(String(6))
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Patient(Base):
    __tablename__ = "patient"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_no: Mapped[str] = mapped_column(String(20), unique=True)
    first_name: Mapped[str] = mapped_column(String(60))
    last_name: Mapped[str] = mapped_column(String(60))
    dob: Mapped[date] = mapped_column(Date)
    location_id: Mapped[int] = mapped_column(ForeignKey("location.id"))
    # Own id when self-guaranteed. Nullable only so seeding can insert before the id is known.
    guarantor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("patient.id"), nullable=True)


class LedgerEntry(Base):
    __tablename__ = "ledger_entry"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id"))
    entry_date: Mapped[date] = mapped_column(Date)
    entry_type: Mapped[str] = mapped_column(String(20))  # charge | payment | adjustment
    payment_type_id: Mapped[Optional[int]] = mapped_column(ForeignKey("payment_type.id"), nullable=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    apply_to: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # todays_visit | account_balance
    amount_cents: Mapped[int] = mapped_column(Integer)  # charges +, payments -, adjustments +/-
    created_by: Mapped[str] = mapped_column(String(60), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime)

    payment_type: Mapped[Optional[PaymentType]] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    event: Mapped[str] = mapped_column(String(40), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(60), default="")
    location_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    location_name: Mapped[str] = mapped_column(String(80), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    result: Mapped[str] = mapped_column(String(10), default="success")  # success | failure | info
    detail: Mapped[str] = mapped_column(Text, default="")


class SettingRow(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
