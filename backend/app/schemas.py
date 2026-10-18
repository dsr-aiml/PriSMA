import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".test", ".invalid")


def normalize_domain(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 2048:
        raise ValueError("Enter a public domain, such as example.com.")
    parsed = urlsplit(value if "://" in value else "https://" + value)
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
        raise ValueError("Only public HTTP(S) domains without credentials are accepted.")
    if parsed.port not in (None, 80, 443) or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("Enter a domain only, without paths, queries, or custom ports.")
    domain = (parsed.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
    labels = domain.split(".")
    if (
        len(domain) > 253
        or len(labels) < 2
        or domain.endswith(BLOCKED_SUFFIXES)
        or not re.fullmatch(r"[a-z]{2,63}|xn--[a-z0-9-]{2,59}", labels[-1])
        or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
    ):
        raise ValueError("Use a public DNS domain. IP addresses and local targets are not accepted.")
    return domain


class Credentials(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def email_valid(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address.")
        return value


class CreateInvestigation(BaseModel):
    domain: str
    depth: Literal["quick", "standard"] = "standard"
    mode: Literal["demo", "live"] = "demo"

    @field_validator("domain")
    @classmethod
    def domain_valid(cls, value):
        return normalize_domain(value)


class FixtureEvidence(BaseModel):
    key: str
    source_url: str
    source_type: str
    category: str
    content: str
    signals: dict


class ProfileUpdate(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-z0-9_-]+$")


class Registration(Credentials, ProfileUpdate):
    pass


class PasswordUpdate(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class ClearWorkspace(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)


class ImportedSource(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    origin: str = Field(min_length=1, max_length=2048)
    format: Literal[
        "text",
        "markdown",
        "html",
        "xml",
        "css",
        "openapi",
        "json",
        "yaml",
        "toml",
        "python",
        "javascript",
        "typescript",
        "sql",
        "dockerfile",
        "config",
        "code",
    ] = "markdown"
    category: Literal[
        "documentation",
        "pricing",
        "api_reference",
        "technical",
        "source_code",
        "configuration",
        "manifest",
        "api_response",
        "data",
        "architecture",
        "runtime_trace",
        "other",
    ] = "documentation"
    content: str = Field(min_length=1, max_length=2000000)

    @field_validator("content")
    @classmethod
    def valid_text(cls, value):
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("Source text contains invalid Unicode code points.") from None
        return value

    @field_validator("origin")
    @classmethod
    def origin_valid(cls, value):
        # Origin labels never cause navigation. Reject executable/link-credential schemes.
        parsed = urlsplit(value)
        if parsed.scheme and parsed.scheme not in ("http", "https", "local"):
            raise ValueError("Use an HTTP(S) source URL or a local filename.")
        if parsed.username or parsed.password or any(ord(c) < 32 for c in value):
            raise ValueError("Source origins cannot contain credentials or control characters.")
        return value


class ImportInvestigation(BaseModel):
    domain: str
    provider: Literal["rules", "ollama", "gemini"] = "rules"
    semantic_retrieval: bool = False
    model_profile: Literal["light", "balanced", "advanced"] = "light"
    sources: list[ImportedSource] = Field(min_length=1, max_length=2000)

    @field_validator("domain")
    @classmethod
    def domain_valid(cls, value):
        return normalize_subject(value)


def normalize_subject(value):
    value = value.strip()
    if not value or len(value) > 253 or any(ord(c) < 32 for c in value):
        raise ValueError("Enter a project name or public domain, up to 253 characters.")
    if "://" in value:
        return normalize_domain(value)
    return value


class BundleAssessment(BaseModel):
    bundle_id: str = Field(min_length=1, max_length=80)
    domain: str
    provider: Literal["rules", "ollama", "gemini"] = "rules"
    semantic_retrieval: bool = False
    model_profile: Literal["light", "balanced", "advanced"] = "light"
    selected: list[str] = Field(min_length=1, max_length=2000)

    @field_validator("domain")
    @classmethod
    def subject_valid(cls, value):
        return normalize_subject(value)


class AskQuestion(BaseModel):
    question: str = Field(min_length=5, max_length=500)
    chat_id: str | None = Field(default=None, max_length=36)
    provider: Literal["rules", "ollama", "gemini"] | None = None
    model_profile: Literal["light", "balanced", "advanced"] = "light"
    semantic_retrieval: bool = False

    @field_validator("question")
    @classmethod
    def meaningful_question(cls, value):
        value = value.strip()
        if len(value) < 5:
            raise ValueError("Enter a question with at least five non-padding characters.")
        return value


class ReanalysisOptions(BaseModel):
    provider: Literal["rules", "ollama", "gemini"] | None = None
    model_profile: Literal["light", "balanced", "advanced"] | None = None
    semantic_retrieval: bool | None = None
    selected: list[str] | None = Field(default=None, min_length=1, max_length=2000)


class RefreshOptions(BaseModel):
    fetch_limit: int | None = Field(default=None, ge=1, le=20)
    search_limit: int | None = Field(default=None, ge=0, le=5)
    direct_read_limit: int | None = Field(default=None, ge=1, le=12)


class WebInvestigation(BaseModel):
    domain: str
    provider: Literal["rules", "ollama", "gemini"] = "rules"
    model_profile: Literal["light", "balanced", "advanced"] = "light"
    semantic_retrieval: bool = False
    source_url: str | None = None
    public_files: bool = True
    browser_observation: bool = False
    browser_page_limit: int = Field(default=3, ge=1, le=5)
    linked_external_scripts: bool = False
    browser_read_operations: bool = False
    browser_interaction_limit: int = Field(default=3, ge=0, le=5)
    refresh_origin: bool = False
    fetch_limit: int = Field(default=6, ge=1, le=20)
    search_limit: int = Field(default=1, ge=0, le=5)
    direct_read_limit: int = Field(default=8, ge=1, le=12)

    @model_validator(mode="before")
    @classmethod
    def target_valid(cls, value):
        value = dict(value)
        target = value.get("source_url") or value.get("domain", "")
        parsed = urlsplit(target if "://" in target else "https://" + target)
        domain = normalize_domain((parsed.scheme or "https") + "://" + parsed.netloc)
        if parsed.fragment or parsed.username or parsed.password or len(target) > 2048:
            raise ValueError("Enter a public HTTP(S) URL without credentials or fragments.")
        value["domain"] = domain
        value["source_url"] = (
            (parsed.scheme or "https")
            + "://"
            + domain
            + (parsed.path or "/")
            + ("?" + parsed.query if parsed.query else "")
        )
        return value

    @field_validator("domain")
    @classmethod
    def domain_valid(cls, value):
        return normalize_domain(value)
