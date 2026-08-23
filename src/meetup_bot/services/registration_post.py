from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from meetup_bot.db.models import Project

_POST_TEXT = (
    "Чтобы зарегистрироваться в проекте, нажмите кнопку ниже — бот откроет "
    "личный чат и запомнит вас как участника."
)
_BUTTON_TEXT = "Зарегистрироваться"


async def sync_registration_post(bot: Bot, project: Project) -> None:
    """Публикует закреплённый пост регистрации с кнопкой-ссылкой `/start
    <invite_payload>` в топик `project.default_thread_id` (TZ §3.3, шаг 3).

    Если пост уже был опубликован раньше (`pinned_message_id` заполнен) —
    публикует новый (топик мог смениться через повторный вызов
    `/setup_registration`, редактировать сообщение в другом топике нельзя) и
    открепляет старый, не давая мигрировать двум запискам-приглашениям
    одновременно."""
    me = await bot.get_me()
    invite_url = f"https://t.me/{me.username}?start={project.invite_payload}"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_BUTTON_TEXT, url=invite_url)]]
    )

    previous_message_id = project.pinned_message_id
    message = await bot.send_message(
        chat_id=project.tg_chat_id,
        message_thread_id=project.default_thread_id,
        text=_POST_TEXT,
        reply_markup=keyboard,
    )
    await bot.pin_chat_message(
        chat_id=project.tg_chat_id, message_id=message.message_id, disable_notification=True
    )
    project.pinned_message_id = message.message_id

    if previous_message_id is not None and previous_message_id != message.message_id:
        try:
            await bot.unpin_chat_message(
                chat_id=project.tg_chat_id, message_id=previous_message_id
            )
        except TelegramBadRequest:
            pass
