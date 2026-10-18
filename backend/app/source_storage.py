"""Database-safe snapshots with lossless original text and stable citation offsets."""

import base64


def normalized_text(value):
    # One Unicode character replaces one NUL. Never delete characters after
    # offsets/chunks are computed, and never present this as the raw original.
    return value.replace("\x00", "\ufffd")


def stored_original(value):
    if "\x00" not in value:
        return value, {}
    return base64.b64encode(value.encode("utf-8")).decode("ascii"), {
        "_original_storage": "base64:utf8",
        "text_normalization": {"nul_replacements": value.count("\x00"), "replacement": "U+FFFD"},
    }


def original_text(source):
    value = getattr(source, "original_content", None)
    if value is None:
        return source.content
    if (getattr(source, "signals", None) or {}).get("_original_storage") == "base64:utf8":
        return base64.b64decode(value, validate=True).decode("utf-8")
    return value


def public_signals(source):
    return {key: value for key, value in (source.signals or {}).items() if not key.startswith("_original_")}
