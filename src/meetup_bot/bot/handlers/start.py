from aiogram import Bot, F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import MembershipRole, RSVPStatus
from meetup_bot.db.models import Event, Project
from meetup_bot.services.projects import ensure_membership, get_or_create_user
from meetup_bot.services.rsvp import (
    RsvpError,
    RsvpOutcome,
    parse_rsvp_start_payload,
    set_rsvp,
)

_NO_PAYLOAD_TEXT = (
    "Чтобы зарегистрироваться в проекте, перейдите по ссылке из поста "
    "регистрации в вашем групповом чате."
)
_UNKNOWN_PAYLOAD_TEXT = (
    "Ссылка регистрации недействительна. Перейдите по ссылке из поста "
    "регистрации в вашем групповом чате."
)
_WELCOME_TEXT = (
    "Вы зарегистрированы в проекте «{project_name}»! Теперь вам будут "
    "приходить сюда личные напоминания от бота."
)
_ALREADY_REGISTERED_TEXT = "Вы уже зарегистрированы в проекте «{project_name}»."

# Хвост приветствия, когда `/start` пришёл по deep-link из-под RSVP-кнопки анонса
# (см. `services/rsvp.py::build_rsvp_start_payload`).
_RSVP_TAIL = {
    RsvpOutcome.GOING: " Ваше участие в мероприятии{event} отмечено ✅",
    RsvpOutcome.NOT_GOING: " Мы отметили, что вы не участвуете в мероприятии{event} ❌",
    RsvpOutcome.CLEARED: " Отметка об участии в мероприятии{event} снята 🤔",
}
_RSVP_TAIL_FAILED = {
    "event_cancelled": " Отметить участие не получилось: мероприятие{event} отменено.",
    "event_finalized": (
        " Отметить участие не получилось: явка на мероприятие{event} уже "
        "зафиксирована."
    ),
}


def _compose_rsvp_start_reply(
    *,
    project_name: str,
    event: Event,
    created: bool,
    outcome: RsvpOutcome | None,
    error: str | None,
) -> str:
    head = (
        _WELCOME_TEXT if created else _ALREADY_REGISTERED_TEXT
    ).format(project_name=project_name)
    event_suffix = f" «{event.title}»" if event.title else ""
    if outcome is not None:
        return head + _RSVP_TAIL[outcome].format(event=event_suffix)
    if error in _RSVP_TAIL_FAILED:
        return head + _RSVP_TAIL_FAILED[error].format(event=event_suffix)
    return head


async def _try_register_with_rsvp(
    message: Message,
    session: AsyncSession,
    bot: Bot,
    *,
    invite_payload: str,
    event_id: int,
    target: RSVPStatus,
) -> bool:
    """Регистрирует вызвавшего в проекте `invite_payload` и ставит RSVP `target`
    на мероприятие `event_id` — путь deep-link из-под RSVP-кнопки анонса. Ставит
    отметку через общий `services/rsvp.py::set_rsvp`, так что живое обновление
    анонса и проверки (отменено/финализировано) переиспользуются.

    Возвращает `False`, если payload не сошёлся с реальным проектом/мероприятием
    (тогда вызывающий разбирает аргумент `/start` как обычный invite-payload)."""
    if message.from_user is None:
        return False

    project = await session.scalar(
        select(Project).where(Project.invite_payload == invite_payload)
    )
    if project is None:
        return False
    event = await session.get(Event, event_id)
    if event is None or event.project_id != project.id:
        return False

    user = await get_or_create_user(
        session,
        tg_user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
    )
    _membership, created = await ensure_membership(
        session, project_id=project.id, user_id=user.id, role=MembershipRole.MEMBER
    )
    await session.flush()

    outcome: RsvpOutcome | None = None
    error: str | None = None
    try:
        outcome = await set_rsvp(
            bot,
            session,
            event_id=event.id,
            tg_user_id=message.from_user.id,
            target=target,
        )
    except RsvpError as exc:
        # Мероприятие отменено/финализировано — в проект всё равно регистрируем,
        # `set_rsvp` до этого ничего не писал, так что коммитим членство сами.
        error = exc.code
        await session.commit()

    await message.answer(
        _compose_rsvp_start_reply(
            project_name=project.name,
            event=event,
            created=created,
            outcome=outcome,
            error=error,
        )
    )
    return True


def create_router() -> Router:
    router = Router(name="start")

    @router.message(CommandStart(), F.chat.type == "private")
    async def on_start(
        message: Message, command: CommandObject, session: AsyncSession, bot: Bot
    ) -> None:
        if message.from_user is None:
            return

        payload = command.args
        if not payload:
            await message.answer(_NO_PAYLOAD_TEXT)
            return

        rsvp_intent = parse_rsvp_start_payload(payload)
        if rsvp_intent is not None:
            invite_payload, event_id, target = rsvp_intent
            if await _try_register_with_rsvp(
                message,
                session,
                bot,
                invite_payload=invite_payload,
                event_id=event_id,
                target=target,
            ):
                return

        project = await session.scalar(
            select(Project).where(Project.invite_payload == payload)
        )
        if project is None:
            await message.answer(_UNKNOWN_PAYLOAD_TEXT)
            return

        user = await get_or_create_user(
            session,
            tg_user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        _membership, created = await ensure_membership(
            session, project_id=project.id, user_id=user.id, role=MembershipRole.MEMBER
        )
        await session.commit()

        text = _WELCOME_TEXT if created else _ALREADY_REGISTERED_TEXT
        await message.answer(text.format(project_name=project.name))

    return router
