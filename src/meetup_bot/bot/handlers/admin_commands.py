from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.enums import MembershipRole, MembershipStatus
from meetup_bot.db.models import Project, ProjectMembership, User
from meetup_bot.services.event_announcement import refresh_member_announcements
from meetup_bot.services.projects import (
    demote_to_member,
    is_project_admin,
    is_project_owner,
    is_rights_gate_satisfied,
    list_active_memberships,
    promote_to_admin,
    remove_membership,
)

_NOT_SET_UP_TEXT = (
    "Бот ещё не настроен в этом чате. Администратор должен вызвать /setup_registration."
)
_NOT_ADMIN_TEXT = "Эту команду может вызвать только администратор проекта."
_NOT_OWNER_TEXT = "Эту команду может вызвать только главный администратор проекта."
_NOT_RIGHTS_TOPIC_TEXT = (
    "Эту команду можно вызвать только из топика регулирования прав проекта."
)
_OWNER_PROTECTED_TEXT = "Нельзя удалить главного администратора проекта."
_NO_MEMBERS_TEXT = "В проекте пока нет зарегистрированных участников."
_NO_REMOVABLE_MEMBERS_TEXT = "Нет участников, которых можно удалить."
_NO_MEMBERS_TO_PROMOTE_TEXT = "Все зарегистрированные участники уже администраторы."
_NO_ADMINS_TO_DEMOTE_TEXT = "В проекте нет со-администраторов, которых можно понизить."
_STALE_ACTION_TEXT = "Действие уже неактуально — участник изменился."

_MEMBERS_HEADER = "Участники проекта «{project_name}»:"
_REMOVE_PROMPT_TEXT = "Кого удалить из проекта?"
_REMOVE_CONFIRM_TEXT = "Удалить {name} из проекта?"
_REMOVED_TEXT = "{name} удалён(а) из проекта."
_REMOVE_CANCELLED_TEXT = "Удаление отменено."

_PROMOTE_PROMPT_TEXT = "Кого назначить администратором?"
_PROMOTE_CONFIRM_TEXT = "Назначить {name} администратором проекта?"
_PROMOTED_TEXT = "{name} назначен(а) администратором проекта."
_PROMOTE_CANCELLED_TEXT = "Назначение отменено."

_DEMOTE_PROMPT_TEXT = "Кого понизить до обычного участника?"
_DEMOTE_CONFIRM_TEXT = "Понизить {name} до обычного участника проекта?"
_DEMOTED_TEXT = "{name} больше не администратор проекта."
_DEMOTE_CANCELLED_TEXT = "Понижение отменено."

_MAX_BUTTON_TEXT_LENGTH = 64

_REMOVE_PICK_PREFIX = "rmm"
_REMOVE_CONFIRM_PREFIX = "rmc"
_REMOVE_CANCEL_DATA = "rmx"
_PROMOTE_PICK_PREFIX = "adm"
_PROMOTE_CONFIRM_PREFIX = "adc"
_PROMOTE_CANCEL_DATA = "adx"
_DEMOTE_PICK_PREFIX = "dad"
_DEMOTE_CONFIRM_PREFIX = "dac"
_DEMOTE_CANCEL_DATA = "dax"


def _display_name_html(user: User) -> str:
    name = escape(user.first_name)
    if user.username:
        return f"{name} (@{escape(user.username)})"
    return name


def _button_text(prefix: str, user: User) -> str:
    """Текст inline-кнопки — обычное поле Telegram, а не HTML, поэтому без
    экранирования; обрезаем на случай длинного имени (лимит кнопки — 64 символа)."""
    label = f"{prefix} {user.first_name}"
    if len(label) > _MAX_BUTTON_TEXT_LENGTH:
        label = label[: _MAX_BUTTON_TEXT_LENGTH - 1] + "…"
    return label


def _role_suffix(role: MembershipRole) -> str:
    if role == MembershipRole.OWNER:
        return " — главный админ"
    if role == MembershipRole.ADMIN:
        return " — админ"
    return ""


async def _rights_gate_blocks(message: Message, session: AsyncSession, project_id: int) -> bool:
    """Гейт по топику `rights` (TZ §3.7) для команд, меняющих права/состав. Если
    гейт не пройден — отвечает пользователю и возвращает `True` (вызов надо
    прервать). Инлайн-кнопки, которые эти команды показывают, рождаются в том же
    топике, что и команда, — отдельной проверки на клик не требуется."""
    satisfied = await is_rights_gate_satisfied(
        session,
        project_id=project_id,
        chat_is_forum=bool(message.chat.is_forum),
        message_thread_id=message.message_thread_id,
    )
    if not satisfied:
        await message.answer(_NOT_RIGHTS_TOPIC_TEXT)
    return not satisfied


def create_router() -> Router:
    router = Router(name="admin_commands")

    @router.message(Command("members"), F.chat.type.in_({"group", "supergroup"}))
    async def on_members(message: Message, session: AsyncSession) -> None:
        if message.from_user is None:
            return

        project = await session.scalar(select(Project).where(Project.tg_chat_id == message.chat.id))
        if project is None:
            await message.answer(_NOT_SET_UP_TEXT)
            return
        if not await is_project_admin(
            session, project_id=project.id, tg_user_id=message.from_user.id
        ):
            await message.answer(_NOT_ADMIN_TEXT)
            return
        if await _rights_gate_blocks(message, session, project.id):
            return

        memberships = await list_active_memberships(session, project_id=project.id)
        if not memberships:
            await message.answer(_NO_MEMBERS_TEXT)
            return

        lines = [_MEMBERS_HEADER.format(project_name=escape(project.name))]
        for index, (membership, user) in enumerate(memberships, start=1):
            lines.append(f"{index}. {_display_name_html(user)}{_role_suffix(membership.role)}")
        await message.answer("\n".join(lines))

    @router.message(Command("remove_member"), F.chat.type.in_({"group", "supergroup"}))
    async def on_remove_member(message: Message, session: AsyncSession) -> None:
        if message.from_user is None:
            return

        project = await session.scalar(select(Project).where(Project.tg_chat_id == message.chat.id))
        if project is None:
            await message.answer(_NOT_SET_UP_TEXT)
            return
        if not await is_project_admin(
            session, project_id=project.id, tg_user_id=message.from_user.id
        ):
            await message.answer(_NOT_ADMIN_TEXT)
            return
        if await _rights_gate_blocks(message, session, project.id):
            return

        memberships = await list_active_memberships(session, project_id=project.id)
        # Главного админа (owner) нельзя удалить — ни другим админом, ни им
        # самим — поэтому его вообще нет в списке кандидатов на удаление.
        removable = [(m, u) for m, u in memberships if m.role != MembershipRole.OWNER]
        if not removable:
            await message.answer(_NO_REMOVABLE_MEMBERS_TEXT)
            return

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_button_text("Удалить", user),
                        callback_data=f"{_REMOVE_PICK_PREFIX}:{membership.id}",
                    )
                ]
                for membership, user in removable
            ]
        )
        await message.answer(_REMOVE_PROMPT_TEXT, reply_markup=keyboard)

    @router.callback_query(F.data.startswith(f"{_REMOVE_PICK_PREFIX}:"))
    async def on_remove_pick(callback: CallbackQuery, session: AsyncSession) -> None:
        if callback.data is None or callback.message is None or callback.from_user is None:
            return

        membership_id = int(callback.data.split(":", 1)[1])
        membership = await session.get(ProjectMembership, membership_id)
        if membership is None or membership.status != MembershipStatus.ACTIVE:
            await callback.answer(_STALE_ACTION_TEXT, show_alert=True)
            return
        # Кнопку видят все участники чата (Bot API не умеет показывать inline-кнопки
        # выборочно) — не-админ, нажавший её, получает всплывающее предупреждение,
        # действие не выполняется (по аналогии с проверкой со-организаторов, TZ §4.3).
        if not await is_project_admin(
            session, project_id=membership.project_id, tg_user_id=callback.from_user.id
        ):
            await callback.answer(_NOT_ADMIN_TEXT, show_alert=True)
            return
        # Список `/remove_member` уже не показывает owner-строки, но callback_data
        # можно сформировать вручную — проверяем ещё раз перед показом подтверждения.
        if membership.role == MembershipRole.OWNER:
            await callback.answer(_OWNER_PROTECTED_TEXT, show_alert=True)
            return

        user = await session.get(User, membership.user_id)
        assert user is not None
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Да, удалить",
                        callback_data=f"{_REMOVE_CONFIRM_PREFIX}:{membership.id}",
                    ),
                    InlineKeyboardButton(text="❌ Отмена", callback_data=_REMOVE_CANCEL_DATA),
                ]
            ]
        )
        await callback.message.edit_text(  # type: ignore[union-attr]
            _REMOVE_CONFIRM_TEXT.format(name=_display_name_html(user)), reply_markup=keyboard
        )
        await callback.answer()

    @router.callback_query(F.data.startswith(f"{_REMOVE_CONFIRM_PREFIX}:"))
    async def on_remove_confirm(
        callback: CallbackQuery, session: AsyncSession, bot: Bot
    ) -> None:
        if callback.data is None or callback.message is None or callback.from_user is None:
            return

        membership_id = int(callback.data.split(":", 1)[1])
        membership = await session.get(ProjectMembership, membership_id)
        if membership is None or membership.status != MembershipStatus.ACTIVE:
            await callback.answer(_STALE_ACTION_TEXT, show_alert=True)
            return
        if not await is_project_admin(
            session, project_id=membership.project_id, tg_user_id=callback.from_user.id
        ):
            await callback.answer(_NOT_ADMIN_TEXT, show_alert=True)
            return
        if membership.role == MembershipRole.OWNER:
            await callback.answer(_OWNER_PROTECTED_TEXT, show_alert=True)
            return

        user = await session.get(User, membership.user_id)
        assert user is not None
        project_id = membership.project_id
        await remove_membership(
            session, membership=membership, removed_by_tg_user_id=callback.from_user.id
        )
        # Убрать удалённого из списка «Участвует» во всех активных анонсах —
        # иначе он висит там (кнопки уже недоступны) до следующего чужого нажатия.
        await refresh_member_announcements(
            bot, session, project_id=project_id, user_id=user.id
        )
        await session.commit()

        await callback.message.edit_text(  # type: ignore[union-attr]
            _REMOVED_TEXT.format(name=_display_name_html(user))
        )
        await callback.answer()

    @router.callback_query(F.data == _REMOVE_CANCEL_DATA)
    async def on_remove_cancel(callback: CallbackQuery) -> None:
        if callback.message is not None:
            await callback.message.edit_text(_REMOVE_CANCELLED_TEXT)  # type: ignore[union-attr]
        await callback.answer()

    @router.message(Command("add_admin"), F.chat.type.in_({"group", "supergroup"}))
    async def on_add_admin(message: Message, session: AsyncSession) -> None:
        if message.from_user is None:
            return

        project = await session.scalar(select(Project).where(Project.tg_chat_id == message.chat.id))
        if project is None:
            await message.answer(_NOT_SET_UP_TEXT)
            return
        # Назначать новых со-админов может только главный админ (owner) — иначе
        # обычный со-админ смог бы бесконтрольно плодить себе равных.
        if not await is_project_owner(
            session, project_id=project.id, tg_user_id=message.from_user.id
        ):
            await message.answer(_NOT_OWNER_TEXT)
            return
        if await _rights_gate_blocks(message, session, project.id):
            return

        memberships = await list_active_memberships(
            session, project_id=project.id, role=MembershipRole.MEMBER
        )
        if not memberships:
            await message.answer(_NO_MEMBERS_TO_PROMOTE_TEXT)
            return

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_button_text("Назначить", user),
                        callback_data=f"{_PROMOTE_PICK_PREFIX}:{membership.id}",
                    )
                ]
                for membership, user in memberships
            ]
        )
        await message.answer(_PROMOTE_PROMPT_TEXT, reply_markup=keyboard)

    @router.callback_query(F.data.startswith(f"{_PROMOTE_PICK_PREFIX}:"))
    async def on_promote_pick(callback: CallbackQuery, session: AsyncSession) -> None:
        if callback.data is None or callback.message is None or callback.from_user is None:
            return

        membership_id = int(callback.data.split(":", 1)[1])
        membership = await session.get(ProjectMembership, membership_id)
        if (
            membership is None
            or membership.status != MembershipStatus.ACTIVE
            or membership.role != MembershipRole.MEMBER
        ):
            await callback.answer(_STALE_ACTION_TEXT, show_alert=True)
            return
        if not await is_project_owner(
            session, project_id=membership.project_id, tg_user_id=callback.from_user.id
        ):
            await callback.answer(_NOT_OWNER_TEXT, show_alert=True)
            return

        user = await session.get(User, membership.user_id)
        assert user is not None
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Да, назначить",
                        callback_data=f"{_PROMOTE_CONFIRM_PREFIX}:{membership.id}",
                    ),
                    InlineKeyboardButton(text="❌ Отмена", callback_data=_PROMOTE_CANCEL_DATA),
                ]
            ]
        )
        await callback.message.edit_text(  # type: ignore[union-attr]
            _PROMOTE_CONFIRM_TEXT.format(name=_display_name_html(user)), reply_markup=keyboard
        )
        await callback.answer()

    @router.callback_query(F.data.startswith(f"{_PROMOTE_CONFIRM_PREFIX}:"))
    async def on_promote_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
        if callback.data is None or callback.message is None or callback.from_user is None:
            return

        membership_id = int(callback.data.split(":", 1)[1])
        membership = await session.get(ProjectMembership, membership_id)
        if (
            membership is None
            or membership.status != MembershipStatus.ACTIVE
            or membership.role != MembershipRole.MEMBER
        ):
            await callback.answer(_STALE_ACTION_TEXT, show_alert=True)
            return
        if not await is_project_owner(
            session, project_id=membership.project_id, tg_user_id=callback.from_user.id
        ):
            await callback.answer(_NOT_OWNER_TEXT, show_alert=True)
            return

        user = await session.get(User, membership.user_id)
        assert user is not None
        promote_to_admin(membership)
        await session.commit()

        await callback.message.edit_text(  # type: ignore[union-attr]
            _PROMOTED_TEXT.format(name=_display_name_html(user))
        )
        await callback.answer()

    @router.callback_query(F.data == _PROMOTE_CANCEL_DATA)
    async def on_promote_cancel(callback: CallbackQuery) -> None:
        if callback.message is not None:
            await callback.message.edit_text(_PROMOTE_CANCELLED_TEXT)  # type: ignore[union-attr]
        await callback.answer()

    @router.message(Command("remove_admin"), F.chat.type.in_({"group", "supergroup"}))
    async def on_remove_admin(message: Message, session: AsyncSession) -> None:
        if message.from_user is None:
            return

        project = await session.scalar(select(Project).where(Project.tg_chat_id == message.chat.id))
        if project is None:
            await message.answer(_NOT_SET_UP_TEXT)
            return
        # Понижать со-админов, как и назначать, может только главный админ
        # (owner) — симметрично `/add_admin` (TZ §4.1).
        if not await is_project_owner(
            session, project_id=project.id, tg_user_id=message.from_user.id
        ):
            await message.answer(_NOT_OWNER_TEXT)
            return
        if await _rights_gate_blocks(message, session, project.id):
            return

        # Кандидаты — только активные со-админы (`role=admin`); владелец
        # (`role=owner`) в список не попадает — его нельзя понизить.
        memberships = await list_active_memberships(
            session, project_id=project.id, role=MembershipRole.ADMIN
        )
        if not memberships:
            await message.answer(_NO_ADMINS_TO_DEMOTE_TEXT)
            return

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_button_text("Понизить", user),
                        callback_data=f"{_DEMOTE_PICK_PREFIX}:{membership.id}",
                    )
                ]
                for membership, user in memberships
            ]
        )
        await message.answer(_DEMOTE_PROMPT_TEXT, reply_markup=keyboard)

    @router.callback_query(F.data.startswith(f"{_DEMOTE_PICK_PREFIX}:"))
    async def on_demote_pick(callback: CallbackQuery, session: AsyncSession) -> None:
        if callback.data is None or callback.message is None or callback.from_user is None:
            return

        membership_id = int(callback.data.split(":", 1)[1])
        membership = await session.get(ProjectMembership, membership_id)
        if (
            membership is None
            or membership.status != MembershipStatus.ACTIVE
            or membership.role != MembershipRole.ADMIN
        ):
            await callback.answer(_STALE_ACTION_TEXT, show_alert=True)
            return
        if not await is_project_owner(
            session, project_id=membership.project_id, tg_user_id=callback.from_user.id
        ):
            await callback.answer(_NOT_OWNER_TEXT, show_alert=True)
            return

        user = await session.get(User, membership.user_id)
        assert user is not None
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Да, понизить",
                        callback_data=f"{_DEMOTE_CONFIRM_PREFIX}:{membership.id}",
                    ),
                    InlineKeyboardButton(text="❌ Отмена", callback_data=_DEMOTE_CANCEL_DATA),
                ]
            ]
        )
        await callback.message.edit_text(  # type: ignore[union-attr]
            _DEMOTE_CONFIRM_TEXT.format(name=_display_name_html(user)), reply_markup=keyboard
        )
        await callback.answer()

    @router.callback_query(F.data.startswith(f"{_DEMOTE_CONFIRM_PREFIX}:"))
    async def on_demote_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
        if callback.data is None or callback.message is None or callback.from_user is None:
            return

        membership_id = int(callback.data.split(":", 1)[1])
        membership = await session.get(ProjectMembership, membership_id)
        if (
            membership is None
            or membership.status != MembershipStatus.ACTIVE
            or membership.role != MembershipRole.ADMIN
        ):
            await callback.answer(_STALE_ACTION_TEXT, show_alert=True)
            return
        if not await is_project_owner(
            session, project_id=membership.project_id, tg_user_id=callback.from_user.id
        ):
            await callback.answer(_NOT_OWNER_TEXT, show_alert=True)
            return

        user = await session.get(User, membership.user_id)
        assert user is not None
        demote_to_member(membership)
        await session.commit()

        await callback.message.edit_text(  # type: ignore[union-attr]
            _DEMOTED_TEXT.format(name=_display_name_html(user))
        )
        await callback.answer()

    @router.callback_query(F.data == _DEMOTE_CANCEL_DATA)
    async def on_demote_cancel(callback: CallbackQuery) -> None:
        if callback.message is not None:
            await callback.message.edit_text(_DEMOTE_CANCELLED_TEXT)  # type: ignore[union-attr]
        await callback.answer()

    return router
