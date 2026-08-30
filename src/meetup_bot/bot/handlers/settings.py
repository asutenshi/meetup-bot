"""`/settings` — просмотр и изменение порогов `ProjectSettings` админом проекта
(задача 4.5, TZ §2.3, §3.4). Минимальный интерфейс: без аргументов бот показывает
текущие значения, с аргументами `<параметр> <значение>` — валидирует и сохраняет.

Порядок проверок — как в `/set_topic` (TZ §3.5): сначала существование проекта и
роль, потом разбор аргументов, иначе не-админ по некорректному вводу увидел бы
подсказку по синтаксису вместо отказа по правам. Гейт топика `rights` (TZ §3.7)
не применяется — он только для команд, меняющих состав и права участников.
"""

from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meetup_bot.db.models import Project, ProjectSettings
from meetup_bot.services.projects import get_or_create_project_settings, is_project_admin

_NOT_SET_UP_TEXT = (
    "Бот ещё не настроен в этом чате. Администратор должен вызвать "
    "/setup_registration."
)
_NOT_ADMIN_TEXT = "Эту команду может вызвать только администратор проекта."


class _InvalidValue(ValueError):
    """Значение не прошло валидацию; текст исключения — готовый ответ пользователю."""


@dataclass(frozen=True)
class _Setting:
    """Один редактируемый параметр `ProjectSettings`. `attr` совпадает с именем
    поля модели и с ключом, который вводит пользователь."""

    attr: str
    describe: str
    parse: Callable[[str], int | str]
    render: Callable[[object], str]


def _int_in_range(attr: str, low: int, high: int) -> Callable[[str], int]:
    def parse(raw: str) -> int:
        try:
            value = int(raw)
        except ValueError:
            raise _InvalidValue(
                f"{attr}: нужно целое число от {low} до {high}."
            ) from None
        if not low <= value <= high:
            raise _InvalidValue(f"{attr}: нужно целое число от {low} до {high}.")
        return value

    return parse


def _parse_timezone(raw: str) -> str:
    try:
        ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError):
        raise _InvalidValue(
            f"Не распознал таймзону «{escape(raw)}». Укажите название из базы IANA, "
            "например Europe/Moscow или Asia/Novosibirsk."
        ) from None
    return raw


_SETTINGS: tuple[_Setting, ...] = (
    _Setting(
        attr="reminder_days_threshold",
        describe="через сколько дней «не виделись» слать личное напоминание участнику",
        parse=_int_in_range("reminder_days_threshold", 1, 365),
        render=str,
    ),
    _Setting(
        attr="missed_events_escalation_count",
        describe=(
            "после скольких пропущенных подряд мероприятий переключаться "
            "с личных напоминаний на эскалацию организатору/админу"
        ),
        parse=_int_in_range("missed_events_escalation_count", 1, 100),
        render=str,
    ),
    _Setting(
        attr="reminder_send_hour",
        describe=(
            "час (0–23) локального времени проекта, в который worker "
            "рассылает напоминания и эскалации"
        ),
        parse=_int_in_range("reminder_send_hour", 0, 23),
        render=str,
    ),
    _Setting(
        attr="timezone",
        describe="таймзона проекта (IANA) для расчёта времени напоминаний",
        parse=_parse_timezone,
        render=str,
    ),
)
_SETTINGS_BY_ATTR = {setting.attr: setting for setting in _SETTINGS}
_KEYS_LINE = ", ".join(setting.attr for setting in _SETTINGS)


def _overview_text(project: Project, settings: ProjectSettings) -> str:
    lines = [f"Настройки проекта «{escape(project.name)}»:", ""]
    for setting in _SETTINGS:
        current = setting.render(getattr(settings, setting.attr))
        lines.append(f"• <code>{setting.attr}</code>: {escape(current)} — {setting.describe}")
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
        setting = _SETTINGS_BY_ATTR.get(key)
        if setting is None:
            await message.answer(
                f"Неизвестный параметр «{escape(key)}». Доступные: {_KEYS_LINE}."
            )
            return
        if len(parts) == 1:
            await message.answer(
                f"Укажите новое значение: <code>/settings {setting.attr} "
                "&lt;значение&gt;</code>."
            )
            return

        try:
            new_value = setting.parse(parts[1].strip())
        except _InvalidValue as exc:
            await message.answer(str(exc))
            return

        old_value = getattr(settings, setting.attr)
        if old_value == new_value:
            await message.answer(
                f"{setting.attr} уже равен {escape(setting.render(new_value))}."
            )
            return

        setattr(settings, setting.attr, new_value)
        await session.commit()
        await message.answer(
            f"Готово. {setting.attr}: {escape(setting.render(old_value))} → "
            f"{escape(setting.render(new_value))}"
        )

    return router
