"""Explicit server-approved profiles, snapshotted with every real investigation."""

from contextlib import contextmanager
from contextvars import ContextVar

from .config import settings

_active = ContextVar("prisma_model_profile", default=None)


def profiles():
    cfg = settings()
    return [
        {
            "id": "light",
            "label": "Lightweight",
            "description": "1–2B class; CPU-first, limited concurrency.",
            "model": cfg.ollama_model,
            "enabled": True,
            "max_bytes": cfg.local_model_max_bytes,
        },
        {
            "id": "balanced",
            "label": "Balanced",
            "description": "3–7B class; requires an explicit server memory budget.",
            "model": cfg.ollama_balanced_model,
            "enabled": cfg.allow_large_local_models and bool(cfg.ollama_balanced_model),
            "max_bytes": cfg.balanced_model_max_bytes,
        },
        {
            "id": "advanced",
            "label": "Advanced",
            "description": "Administrator-selected model; verify RAM and GPU capacity before use.",
            "model": cfg.ollama_advanced_model,
            "enabled": cfg.allow_large_local_models and bool(cfg.ollama_advanced_model),
            "max_bytes": cfg.advanced_model_max_bytes,
        },
    ]


def snapshot(provider, profile="light", *, purpose="assessment"):
    from .model_gateway import ModelFailure, ensure_enabled, model_identity

    ensure_enabled(provider, purpose=purpose)
    cfg = settings()
    selected = next((p for p in profiles() if p["id"] == profile), None)
    if not selected or (provider == "ollama" and not selected["enabled"]):
        raise ModelFailure("This local profile is not enabled by the inference server administrator.")
    return {
        "purpose": purpose,
        "profile": profile,
        "model": selected["model"]
        if provider == "ollama"
        else (cfg.gemini_query_model if purpose == "query" else cfg.gemini_model)
        if provider == "gemini"
        else model_identity("rules"),
        "embedding_model": cfg.ollama_embedding_model
        if provider == "ollama"
        else cfg.gemini_embedding_model
        if provider == "gemini"
        else None,
        "max_bytes": selected["max_bytes"],
        "memory_budget_bytes": cfg.inference_memory_budget_bytes,
        "context_tokens": cfg.gemini_query_context_tokens if provider == "gemini" and purpose == "query" else cfg.model_context_tokens,
        "output_tokens": cfg.gemini_query_output_tokens if provider == "gemini" and purpose == "query" else cfg.model_output_tokens,
        "threads": cfg.model_threads,
        "gpu_layers": cfg.local_gpu_layers if provider == "ollama" else 0,
    }


def active(provider="ollama"):
    return _active.get() or snapshot(provider)


def purpose():
    return (_active.get() or {}).get("purpose", "assessment")


@contextmanager
def using(options):
    # Existing reports without a profile retain the old configured default.
    token = _active.set((options or {}).get("model_settings"))
    try:
        yield
    finally:
        _active.reset(token)
