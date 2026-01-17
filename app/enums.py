from enum import Enum


class ItemStatus(str, Enum):
    REPORTED = "REPORTED"
    COLLECTED = "COLLECTED"
    IN_STORAGE = "IN_STORAGE"
    SENT_TO_VENDOR = "SENT_TO_VENDOR"
    RECYCLED = "RECYCLED"
    DISPOSED = "DISPOSED"


class CategoryType(str, Enum):
    RECYCLABLE = "RECYCLABLE"
    REUSABLE = "REUSABLE"
    HAZARDOUS = "HAZARDOUS"


class UserRole(str, Enum):
    USER = "USER"
    ADMIN = "ADMIN"
    VENDOR = "VENDOR"








