"""`/settings` — просмотр и изменение порогов `ProjectSettings` админом проекта
(задача 4.5, TZ §2.3, §3.4). Минимальный интерфейс: без аргументов бот показывает
текущие значения, с аргументами `<параметр> <значение>` — валидирует и сохраняет.

Порядок проверок — как в `/set_topic` (TZ §3.5): сначала существование проекта и
роль, потом разбор аргументов, иначе не-админ по некорректному вводу увидел бы
подсказку по синтаксису вместо отказа по правам. Гейт топика `rights` (TZ §3.7)
не применяется — он только для команд, меняющих состав и права участников.

Реестр параметров и их валидация — общий `services.project_settings` (тот же
источник правды, что у Web App-экрана настроек). Здесь остаётся только
presentation команды.
"""

from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.models import Project, ProjectSettings
from meetup_bot.services.project_settings import (
    EDITABLE_SETTINGS,
    SETTINGS_BY_ATTR,
    SettingValueError,
    parse_setting,
)
from meetup_bot.services.projects import get_or_create_project_settings, is_project_admin

_NOT_SET_UP_TEXT = (
    "Бот ещё не настроен в этом чате. Администратор должен вызвать "
    "/setup_registration."
)
_NOT_ADMIN_TEXT = "Эту команду может вызвать только администратор проекта."

_KEYS_LINE = ", ".join(spec.attr for spec in EDITABLE_SETTINGS)


def _overview_text(project: Project, settings: ProjectSettings) -> str:
    lines = [f"Настройки проекта «{escape(project.name)}»:", ""]
    for spec in EDITABLE_SETTINGS:
        current = str(getattr(settings, spec.attr))
        lines.append(f"• <code>{spec.attr}</code>: {escape(current)} — {spec.describe}")
    lines.append("")
    lines.append("Изменить: <code>/settings &lt;параметр&gt; &lt;значение&gt;</code>")
    lines.append("Например: <code>/settings reminder_send_hour 19</code>")
    return "\n".join(lines)


def create_router() -> Router:
    router = Router(name="settings")

    @router.message(Command("settings"), F.chat.type.in_({"group", "supergroup"}))
    async def on_settings(
        message: Message, command: CommandObject, session: AsyncSession
    ) -> None:
        if message.from_user is None:
            return

        project = await session.scalar(
            select(Project).where(Project.tg_chat_id == message.chat.id)
        )
        if project is None:
            await message.answer(_NOT_SET_UP_TEXT)
            return

        if not await is_project_admin(
            session, project_id=project.id, tg_user_id=message.from_user.id
        ):
            await message.answer(_NOT_ADMIN_TEXT)
            return

        settings = await get_or_create_project_settings(session, project_id=project.id)

        raw = (command.args or "").strip()
        if not raw:
            await message.answer(_overview_text(project, settings))
            return

        parts = raw.split(maxsplit=1)
        key = parts[0]
        spec = SETTINGS_BY_ATTR.get(key)
        if spec is None:
            await message.answer(
                f"Неизвестный параметр «{escape(key)}». Доступные: {_KEYS_LINE}."
            )
            return
        if len(parts) == 1:
            await message.answer(
                f"Укажите новое значение: <code>/settings {spec.attr} "
                "&lt;значение&gt;</code>."
            )
            return

        try:
            new_value = parse_setting(spec.attr, parts[1])
        except SettingValueError as exc:
            await message.answer(str(exc))
            return

        old_value = getattr(settings, spec.attr)
        if old_value == new_value:
            await message.answer(f"{spec.attr} уже равен {escape(str(new_value))}.")
            return

        setattr(settings, spec.attr, new_value)
        await session.commit()
        await message.answer(
            f"Готово. {spec.attr}: {escape(str(old_value))} → {escape(str(new_value))}"
        )

    return router
