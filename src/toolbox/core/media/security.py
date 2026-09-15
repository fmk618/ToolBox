"""URL and resource validation for media inputs."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from ..errors import MediaValidationError

YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"})
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
MAX_URL_LENGTH = 2_048


def _hostname(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise MediaValidationError("网址格式无效") from exc
    if not host:
        raise MediaValidationError("网址缺少主机名")
    if parsed.username is not None or parsed.password is not None:
        raise MediaValidationError("网址不允许包含用户名或密码")
    if port is not None:
        raise MediaValidationError("网址不允许指定端口")
    return host.rstrip(".").lower()


def _valid_video_id(value: str) -> str:
    if not _VIDEO_ID.fullmatch(value):
        raise MediaValidationError("YouTube 视频 ID 无效")
    return value


def extract_youtube_id(value: str) -> str:
    """Extract a single YouTube video ID without retaining user query data."""
    if len(value) > MAX_URL_LENGTH:
        raise MediaValidationError("网址过长")
    try:
        parsed = urlsplit(value.strip())
        host = _hostname(value)
    except MediaValidationError:
        raise
    if parsed.scheme.lower() != "https":
        raise MediaValidationError("视频网址必须使用 HTTPS")
    if parsed.fragment:
        raise MediaValidationError("视频网址不允许包含片段标识")
    if host not in YOUTUBE_HOSTS:
        raise MediaValidationError("目前仅支持 YouTube 视频网址")

    if host == "youtu.be":
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 1 or parsed.query:
            raise MediaValidationError("youtu.be 网址格式无效")
        return _valid_video_id(parts[0])

    parts = [part for part in parsed.path.split("/") if part]
    if parts == ["watch"]:
        values = parse_qs(parsed.query, keep_blank_values=True).get("v", [])
        if len(values) != 1:
            raise MediaValidationError("YouTube watch 网址缺少视频 ID")
        return _valid_video_id(values[0])
    if len(parts) == 2 and parts[0] in {"shorts", "embed", "live"} and not parsed.query:
        return _valid_video_id(parts[1])
    raise MediaValidationError("YouTube 视频网址格式无效")


def canonical_youtube_url(video_id: str) -> str:
    return "https://www.youtube.com/watch?" + urlencode({"v": _valid_video_id(video_id)})


def _is_public_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError as exc:
        raise MediaValidationError("远程主机地址无效") from exc
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_global
        and not ip.is_loopback
        and not ip.is_private
        and not ip.is_link_local
        and not ip.is_reserved
        and not ip.is_multicast
        and not ip.is_unspecified
    )


def validate_public_url(value: str, allowed_hosts: set[str] | frozenset[str] | None = None) -> str:
    """Validate a remote media URL before handing it to a downloader."""
    if len(value) > MAX_URL_LENGTH:
        raise MediaValidationError("网址过长")
    try:
        parsed = urlsplit(value.strip())
        host = _hostname(value)
    except MediaValidationError:
        raise
    if parsed.scheme.lower() != "https":
        raise MediaValidationError("远程媒体网址必须使用 HTTPS")
    if parsed.fragment:
        raise MediaValidationError("远程媒体网址不允许包含片段标识")
    if allowed_hosts is not None and host not in {h.lower().rstrip(".") for h in allowed_hosts}:
        raise MediaValidationError("该视频来源暂不支持")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise MediaValidationError("不允许访问本地主机")

    try:
        direct_ip = ipaddress.ip_address(host)
    except ValueError:
        direct_ip = None
    if direct_ip is not None:
        if not _is_public_ip(str(direct_ip)):
            raise MediaValidationError("不允许访问内网地址")
    else:
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
            }
        except OSError as exc:
            raise MediaValidationError("无法解析远程主机") from exc
        if not addresses or not all(_is_public_ip(address) for address in addresses):
            raise MediaValidationError("远程主机解析到了不允许的地址")
    return urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))


def redact_url(value: str) -> str:
    """Return a log-safe URL without query or fragment data."""
    try:
        parsed = urlsplit(value)
        return urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", ""))
    except ValueError:
        return "<invalid-url>"
