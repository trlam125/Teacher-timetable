from app.services.runtime import (
    Assignment,
    Department,
    Grade,
    SchoolClass,
    Subject,
    Teacher,
)

ENTITY_MODELS = {
    "department": Department,
    "subject": Subject,
    "teacher": Teacher,
    "grade": Grade,
    "class": SchoolClass,
    "assignment": Assignment,
}

__all__ = ["ENTITY_MODELS"]
