"""Bounded public file reads, pinned to validated public addresses."""

import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

import httpx


class PublicFileError(ValueError):
    pass


def public_address(host):
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    except OSError as exc:
        raise PublicFileError("Public hostname could not be resolved.") from exc
    if not addresses or any(
        not ipaddress.ip_address(value).is_global or ipaddress.ip_address(value).is_multicast
        for value in addresses
    ):
        raise PublicFileError("The URL does not resolve exclusively to public addresses.")
    return addresses[0]


def read_public(
    url,
    *,
    allowed_hosts,
    max_bytes=800000,
    before_request=lambda: None,
    transport=None,
    resolver=public_address,
    include_headers=False,
    timeout_seconds=30,
    allow_statuses=(200,),
    method="GET",
    request_body=None,
    user_agent=None,
):
    """Validate each redirect and pin the socket address while retaining TLS SNI."""
    if method != "GET":
        from .read_operations import validate_read_operation
        if method != "POST":
            raise PublicFileError("Only anonymous reads are permitted.")
        try:
            validate_read_operation(request_body)
        except ValueError as exc:
            raise PublicFileError(str(exc)) from exc
    elif request_body is not None:
        raise PublicFileError("GET bodies are not admitted.")
    if user_agent is not None and (not isinstance(user_agent, str) or not 1 <= len(user_agent) <= 512 or any(ord(c) < 32 or ord(c) > 126 for c in user_agent)):
        raise PublicFileError("Invalid browser user agent.")
    for _ in range(4):
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        segments = [unquote(part).casefold() for part in parsed.path.split("/")]
        if any(part.startswith(".env") or part in {"credentials.json", "service-account.json", "id_rsa", "id_ed25519"} or part.endswith((".pem", ".key", ".p12", ".pfx")) for part in segments):
            raise PublicFileError("Credential files are outside the public reader scope.")
        if (
            parsed.scheme not in ("http", "https")
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 80, 443)
            or not any(host == scope or host.endswith("." + scope) for scope in allowed_hosts)
        ):
            raise PublicFileError("Public file redirect is outside the selected scope.")
        address = resolver(host)
        if not ipaddress.ip_address(address).is_global or ipaddress.ip_address(address).is_multicast:
            raise PublicFileError("Non-public target address.")
        netloc = "[" + address + "]" if ":" in address else address
        pinned = urlunsplit(
            (
                parsed.scheme,
                netloc + (":" + str(parsed.port) if parsed.port else ""),
                parsed.path or "/",
                parsed.query,
                "",
            )
        )
        before_request()
        try:
            with httpx.Client(
                timeout=httpx.Timeout(timeout_seconds, connect=min(8, timeout_seconds)),
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client:
                with client.stream(
                    method,
                    pinned,
                    headers={
                        "Host": parsed.netloc,
                        "User-Agent": user_agent or "PriSMA/0.8.3 public-evidence-reader",
                        "Accept": "text/html, application/json, text/plain, */*;q=0.5",
                        **({"Content-Type": "application/json"} if method == "POST" else {}),
                    },
                    content=request_body,
                    extensions={"sni_hostname": host},
                ) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        if method != "GET":
                            raise PublicFileError("Read operation redirects are excluded.")
                        location = response.headers.get("location")
                        if not location:
                            raise PublicFileError("Public file redirect has no destination.")
                        url = urljoin(url, location)
                        continue
                    if response.status_code not in allow_statuses:
                        raise PublicFileError(f"Public file returned HTTP {response.status_code}.")
                    body = bytearray()
                    for block in response.iter_bytes():
                        body.extend(block)
                        if len(body) > max_bytes:
                            raise PublicFileError("Public file exceeds the byte budget.")
                    result = (bytes(body), url, response.headers.get("content-type", ""))
                    if include_headers:
                        # Transport controls and cookies are deliberately excluded.
                        headers = {key: value[:1000] for key, value in response.headers.items()
                                   if key in {"content-type", "server", "x-powered-by", "x-vercel-id", "x-vercel-cache", "cf-ray", "via", "cache-control", "strict-transport-security", "content-security-policy", "access-control-allow-origin", "access-control-allow-credentials", "sourcemap", "x-sourcemap"}}
                        return (*result, headers, response.status_code)
                    return result
        except httpx.HTTPError as exc:
            raise PublicFileError("Public file could not be read within the request timeout.") from exc
    raise PublicFileError("Public file redirect limit reached.")


def decode_public_text(raw, content_type=""):
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    match = re.search(r"charset\s*=\s*['\"]?([\w-]+)", content_type, re.I)
    if not match and "html" in content_type:
        match = re.search(r"charset\s*=\s*['\"]?([\w-]+)", raw[:4096].decode("ascii", errors="ignore"), re.I)
    encoding = match[1].casefold() if match else "utf-8-sig"
    aliases = {"utf-8": "utf-8-sig", "utf8": "utf-8-sig", "iso-8859-1": "cp1252", "windows-1252": "cp1252", "us-ascii": "ascii"}
    encoding = aliases.get(encoding, encoding)
    if encoding not in {"utf-8-sig", "utf-16", "utf-16le", "utf-16be", "cp1252", "ascii"}:
        raise PublicFileError("The public document declares an unsupported character encoding.")
    return raw.decode(encoding)


class LinkedFiles(HTMLParser):
    def __init__(self, base):
        super().__init__()
        self.base, self.links, self.resources = base, [], []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        reference = (
            values.get("src") if tag == "script" else values.get("href") if tag in ("a", "link") else None
        )
        if reference and (
            tag == "script" or (tag == "link" and values.get("rel", "").casefold() in {"stylesheet", "modulepreload", "manifest", "sitemap"})
            or any(
                word in reference.casefold()
                for word in ("openapi", "swagger", "schema", "architecture", "package.json")
            )
        ):
            url = urljoin(self.base, reference)
            self.links.append(url)
            kind = "script" if tag == "script" or values.get("rel") == "modulepreload" else "stylesheet" if values.get("rel") == "stylesheet" else "manifest" if values.get("rel") == "manifest" else "sitemap" if values.get("rel") == "sitemap" else "document"
            self.resources.append({"url": url, "kind": kind})


def repository_archive(url):
    parsed = urlsplit(url)
    parts = parsed.path.strip("/").split("/")
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or len(parts) < 2
        or not all(part and part not in (".", "..") for part in parts)
    ):
        raise PublicFileError(
            "Use a public https://github.com/owner/repository URL, optionally followed by /tree/branch."
        )
    owner, repo = parts[:2]
    if not all(all(c.isalnum() or c in "-_." for c in value) for value in (owner, repo)):
        raise PublicFileError("Invalid repository owner or name.")
    if len(parts) == 2:
        branch = "HEAD"
    elif len(parts) >= 4 and parts[2] == "tree":
        branch = "/".join(parts[3:])
    else:
        raise PublicFileError("Use the repository root or a /tree/branch URL.")
    return (
        f"https://codeload.github.com/{owner}/{repo.removesuffix('.git')}/zip/{quote(branch, safe='')}",
        repo.removesuffix(".git") + ".zip",
    )
