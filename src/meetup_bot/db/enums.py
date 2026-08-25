import enum


class TopicCategory(enum.Enum):
    EVENTS = "events"
    MONEY_COLLECTIONS = "money_collections"
    GENERAL = "general"


class MembershipRole(enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class MembershipStatus(enum.Enum):
    ACTIVE = "active"
    REMOVED = "removed"
