import enum


class TopicCategory(enum.Enum):
    EVENTS = "events"
    MONEY_COLLECTIONS = "money_collections"
    GENERAL = "general"
    # Не про маршрутизацию исходящих сообщений, а про то, откуда разрешено
    # вызывать admin-команды регулирования прав (TZ §3.7). Привязывается тем же
    # `/set_topic`, но не участвует в `resolve_thread_id`.
    RIGHTS = "rights"


class MembershipRole(enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class MembershipStatus(enum.Enum):
    ACTIVE = "active"
    REMOVED = "removed"
