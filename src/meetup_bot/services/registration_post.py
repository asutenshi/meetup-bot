from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from meetup_bot.db.models import Project

_POST_TEXT = (
    "Чтобы зарегистрироваться в проекте, нажмите кнопку ниже — бот откроет "
    "личный чат и запомнит вас как участника."
)
_BUTTON_TEXT = "Зарегистрироваться"
_PIN_REMINDER = (
    "Закрепите этот пост вручную (меню чата → «Закрепить сообщение»), чтобы "
    "он был виден всем участникам."
)


async def sync_registration_post(bot: Bot, project: Project) -> None:
    """Публикует пост регистрации с кнопкой-ссылкой `/start <invite_payload>`
    в топик `project.default_thread_id` (TZ §3.3, шаг 3). Закрепление —
    полностью на ответственности администратора чата: бот не закрепляет пост
    сам и не трогает закрепление старого поста при повторной публикации (не
    знает, закреплял ли его админ вообще).

    Если пост уже был опубликован раньше (`pinned_message_id` заполнен) —
    публикует новый (топик мог смениться через повторный вызов
    `/setup_registration`, редактировать сообщение в другом топике нельзя);
    старый пост при этом не трогается — при переносе топика админ сам решает,
    что делать со старым постом."""
    me = await bot.get_me()
    invite_url = f"https://t.me/{me.username}?start={project.invite_payload}"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=_BUTTON_TEXT, url=invite_url)]]
    )

    message = await bot.send_message(
        chat_id=project.tg_chat_id,
        message_thread_id=project.default_thread_id,
        text=_POST_TEXT,
        reply_markup=keyboard,
    )
    await bot.send_message(
        chat_id=project.tg_chat_id,
        message_thread_id=project.default_thread_id,
        text=_PIN_REMINDER,
    )
    project.pinned_message_id = message.message_id
