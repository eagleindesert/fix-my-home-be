"""HTTP 접근 로그와 gzip 회전. ASGI 응답 완료까지의 시간을 기록한다."""

import gzip
import ipaddress
import json
import logging
import shutil
import time
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from uuid import uuid4


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {"timestamp": datetime.now(UTC).isoformat(), "level": record.levelname,
                   "logger": record.name, "message": record.getMessage()}
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(settings, service="api"):
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("fmh." + service)
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()
    handler = RotatingFileHandler(settings.log_dir / f"{service}.log", encoding="utf-8",
                                  maxBytes=settings.log_max_bytes, backupCount=settings.log_backups)
    handler.namer = lambda name: name + ".gz"

    def compress(source, destination):
        with open(source, "rb") as src, gzip.open(destination, "wb") as dst:
            shutil.copyfileobj(src, dst)
        from pathlib import Path
        Path(source).unlink()

    handler.rotator = compress
    stream = logging.StreamHandler()
    for output in (handler, stream):
        output.setFormatter(JsonFormatter())
        logger.addHandler(output)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def client_ip(peer, headers, trusted):
    def parse(value):
        try:
            return ipaddress.ip_address(value.strip())
        except ValueError:
            return None

    networks = [ipaddress.ip_network(value.strip(), strict=False) for value in trusted.split(",") if value.strip()]

    def is_trusted(value):
        address = parse(value)
        return address is not None and any(address in network for network in networks)

    if not is_trusted(peer):
        return peer
    forwarded = headers.get("x-forwarded-for", "")
    if forwarded:
        hops = forwarded.split(",")
        if all(parse(hop) for hop in hops):
            for hop in reversed(hops):
                if not is_trusted(hop):
                    return str(parse(hop))
            return str(parse(hops[0]))
    real = parse(headers.get("x-real-ip", ""))
    return str(real) if real else peer


class AccessLogMiddleware:
    def __init__(self, app, settings, logger, error_handler=None):
        self.app, self.settings, self.logger = app, settings, logger
        self.error_handler = error_handler

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        start = time.monotonic()
        status = 500
        response_started = False
        state = scope.setdefault("state", {})
        state["request_id"] = str(uuid4())
        headers = {k.decode().lower(): v.decode("latin-1") for k, v in scope["headers"]}
        peer = scope.get("client", ("unknown", 0))[0]

        async def capture(message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-request-id", state["request_id"].encode()),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        except Exception as error:
            if response_started or self.error_handler is None:
                raise
            from starlette.requests import Request
            response = await self.error_handler(Request(scope, receive), error)
            await response(scope, receive, capture)
        finally:
            self.logger.info("http.request", extra={"fields": {
                "method": scope["method"], "uri": scope["path"], "statusCode": status,
                "clientIp": client_ip(peer, headers, self.settings.trusted_proxy_ips),
                "userId": state.get("user_id"), "requestId": state["request_id"],
                "elapsedMs": round((time.monotonic() - start) * 1000, 3),
            }})
