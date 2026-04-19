from __future__ import annotations

from typing import Any, Dict


LEGACY_TO_BINARY_STATUS = {
    "VERIFIED": "VERIFIED",
    "REJECTED": "REJECTED",
    "WARNING": "VERIFIED",
    "INSUFFICIENT_CONTEXT": "VERIFIED",
    "ERROR": "REJECTED",
    "PENDING": "VERIFIED",
}


def normalize_validation_status(value: Any, default: str = "REJECTED") -> str:
    normalized = str(value or "").strip().upper()
    if not normalized:
        return default
    return LEGACY_TO_BINARY_STATUS.get(normalized, default)


def normalize_validation_record(record: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(record)
    if "validation_status" in normalized:
        normalized["validation_status"] = normalize_validation_status(normalized.get("validation_status"))
    return normalized
