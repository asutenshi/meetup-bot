import datetime
import decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from meetup_bot.db.base import Base
from meetup_bot.db.enums import (
    EventStatus,
    MembershipRole,
    MembershipStatus,
    RSVPStatus,
    TopicCategory,
)


def _enum_column(enum_cls: type) -> Enum:
    # `VARCHAR` + `CHECK` вместо нативного типа Postgres ENUM (TZ §2, вводная
    # часть) — набор значений расширяется обычной Alembic-миграцией, без
    # пересоздания типа.
    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda cls: [member.value for member in cls],
    )


class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    name: Mapped[str] = mapped_column(String)
    invite_payload: Mapped[str] = mapped_column(String, unique=True)
    pinned_message_id: Mapped[int | None] = mapped_column(BigInteger)
    default_thread_id: Mapped[int | None] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    topic_settings: Mapped[list["ProjectTopicSetting"]] = relationship(back_populates="project")
    settings: Mapped["ProjectSettings"] = relationship(back_populates="project")
    memberships: Mapped[list["ProjectMembership"]] = relationship(
        back_populates="project", foreign_keys="ProjectMembership.project_id"
    )


class ProjectTopicSetting(Base):
    __tablename__ = "project_topic_setting"
    __table_args__ = (UniqueConstraint("project_id", "category"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"))
    category: Mapped[TopicCategory] = mapped_column(_enum_column(TopicCategory))
    thread_id: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="topic_settings")


class ProjectSettings(Base):
    __tablename__ = "project_settings"

    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), primary_key=True)
    reminder_days_threshold: Mapped[int] = mapped_column(Integer, default=14, server_default="14")
    unfilled_checklist_hours: Mapped[int] = mapped_column(Integer, default=24, server_default="24")
    missed_events_escalation_count: Mapped[int] = mapped_column(
        Integer, default=3, server_default="3"
    )
    all_command_throttle_seconds: Mapped[int] = mapped_column(
        Integer, default=180, server_default="180"
    )
    timezone: Mapped[str] = mapped_column(
        String, default="Europe/Moscow", server_default="Europe/Moscow"
    )
    # Час локального времени проекта (`timezone`), в который worker рассылает
    # личные напоминания и эскалации (TZ §2.3, §3.4 п.2–3) — чтобы уведомления
    # не приходили ночью. Финализации явки (п.1) не касается.
    reminder_send_hour: Mapped[int] = mapped_column(Integer, default=20, server_default="20")
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="settings")


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(String)
    first_name: Mapped[str] = mapped_column(String)
    last_name: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProjectMembership(Base):
    __tablename__ = "project_membership"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    role: Mapped[MembershipRole] = mapped_column(_enum_column(MembershipRole))
    status: Mapped[MembershipStatus] = mapped_column(
        _enum_column(MembershipStatus),
        default=MembershipStatus.ACTIVE,
        server_default=MembershipStatus.ACTIVE.value,
    )
    registered_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    removed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    last_attended_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_missed_events: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Троттлинг личных напоминаний «давно не виделись» (TZ §3.4 п.2): не чаще
    # одного напоминания в день на участника. Проставляется worker'ом.
    last_reminder_sent_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    # Троттлинг эскалации организатору/админу (TZ §3.4 п.3): не чаще одной
    # эскалации в неделю на пару участник—проект. Проставляется worker'ом.
    last_escalation_sent_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    project: Mapped["Project"] = relationship(
        back_populates="memberships", foreign_keys=[project_id]
    )
    user: Mapped["User"] = relationship(foreign_keys=[user_id])


class Event(Base):
    __tablename__ = "event"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"))
    title: Mapped[str | None] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    # Опциональное окончание для многодневных мероприятий; `null` — считаем
    # эффективным окончанием `starts_at`. Влияет только на момент финализации
    # явки (TZ §2.6, §3.4), не на RSVP/анонс.
    ends_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    location: Mapped[str] = mapped_column(String)
    budget_per_person: Mapped[decimal.Decimal | None] = mapped_column(Numeric(10, 2))
    seats_limit: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[EventStatus] = mapped_column(
        _enum_column(EventStatus),
        default=EventStatus.PLANNED,
        server_default=EventStatus.PLANNED.value,
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("user.id"))
    announcement_message_id: Mapped[int | None] = mapped_column(BigInteger)
    # Проставляется воркером при финализации явки (TZ §2.6, §3.4, п.1). Пока
    # `null` — мероприятие не финализировано, RSVP можно свободно править.
    attendance_finalized_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship()
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])
    co_organizers: Mapped[list["EventCoOrganizer"]] = relationship(back_populates="event")
    rsvps: Mapped[list["EventRSVP"]] = relationship(back_populates="event")


class EventCoOrganizer(Base):
    __tablename__ = "event_co_organizer"
    __table_args__ = (UniqueConstraint("event_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("event.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    added_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    event: Mapped["Event"] = relationship(back_populates="co_organizers")
    user: Mapped["User"] = relationship(foreign_keys=[user_id])


class EventRSVP(Base):
    __tablename__ = "event_rsvp"
    __table_args__ = (UniqueConstraint("event_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("event.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    status: Mapped[RSVPStatus] = mapped_column(_enum_column(RSVPStatus))
    responded_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Кто последним менял статус: сам участник (тогда `== user_id`) либо
    # организатор/создатель/админ при постфактум-правке (TZ §2.8, §3.4, п.1).
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    event: Mapped["Event"] = relationship(back_populates="rsvps")
    user: Mapped["User"] = relationship(foreign_keys=[user_id])
