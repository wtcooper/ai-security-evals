#!/usr/bin/env python3
"""A small RFC 6455 WebSocket client and server on the standard library.

It exists so the realtime adapter, the mock realtime server and the tests need no package.
It handles what a JSON-event realtime API uses: text messages of any size, fragmented
messages, ping/pong, close, TLS (`wss://`), request headers, and an HTTPS proxy from
HTTPS_PROXY (CONNECT). It does not implement compression extensions or binary subprotocols.
"""
from __future__ import annotations

import base64
import hashlib
import os
import socket
import socketserver
import ssl
import struct
import threading
from urllib.parse import urlsplit

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA


class WebSocketError(Exception):
    """Handshake or protocol failure. `status` is the HTTP status when the upgrade was
    refused (for example 401 for a missing or wrong key)."""

    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


class ConnectionClosed(WebSocketError):
    pass


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


def _xor(payload: bytes, mask: bytes) -> bytes:
    n = len(payload)
    if n == 0:
        return b""
    keys = (mask * (n // 4 + 1))[:n]
    return (int.from_bytes(payload, "big") ^ int.from_bytes(keys, "big")).to_bytes(n, "big")


def encode_frame(opcode: int, payload: bytes, masked: bool, fin: bool = True) -> bytes:
    head = bytes([(0x80 if fin else 0) | opcode])
    n = len(payload)
    mask_bit = 0x80 if masked else 0
    if n < 126:
        head += bytes([mask_bit | n])
    elif n < 1 << 16:
        head += bytes([mask_bit | 126]) + struct.pack("!H", n)
    else:
        head += bytes([mask_bit | 127]) + struct.pack("!Q", n)
    if not masked:
        return head + payload
    mask = os.urandom(4)
    return head + mask + _xor(payload, mask)


class Connection:
    """One open WebSocket, either side. Clients mask what they send; servers do not."""

    def __init__(self, sock: socket.socket, is_client: bool, leftover: bytes = b""):
        self._sock = sock
        self._is_client = is_client
        self._buf = leftover
        self._send_lock = threading.Lock()
        self.closed = False

    def _read(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self._sock.recv(65536)
            if not chunk:
                self.closed = True
                raise ConnectionClosed("connection closed by peer")
            self._buf += chunk
        data, self._buf = self._buf[:n], self._buf[n:]
        return data

    def _read_frame(self) -> tuple[bool, int, bytes]:
        b0, b1 = self._read(2)
        fin, opcode = bool(b0 & 0x80), b0 & 0x0F
        masked, n = bool(b1 & 0x80), b1 & 0x7F
        if n == 126:
            n = struct.unpack("!H", self._read(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", self._read(8))[0]
        mask = self._read(4) if masked else None
        payload = self._read(n)
        return fin, opcode, _xor(payload, mask) if mask else payload

    def _send(self, opcode: int, payload: bytes) -> None:
        with self._send_lock:
            self._sock.sendall(encode_frame(opcode, payload, masked=self._is_client))

    def send(self, text: str) -> None:
        if self.closed:
            raise ConnectionClosed("connection is closed")
        self._send(OP_TEXT, text.encode())

    def recv(self) -> str:
        """The next complete text message. Answers pings; raises ConnectionClosed on close."""
        parts: list[bytes] = []
        while True:
            fin, opcode, payload = self._read_frame()
            if opcode == OP_PING:
                self._send(OP_PONG, payload)
            elif opcode == OP_PONG:
                continue
            elif opcode == OP_CLOSE:
                self.closed = True
                try:
                    self._send(OP_CLOSE, payload[:2])
                except OSError:
                    pass
                code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else None
                raise ConnectionClosed(f"closed by peer (code {code}): "
                                       f"{payload[2:].decode(errors='replace')}")
            elif opcode in (OP_TEXT, OP_BINARY, OP_CONT):
                parts.append(payload)
                if fin:
                    return b"".join(parts).decode(errors="replace")
            else:
                raise WebSocketError(f"unexpected opcode {opcode}")

    def close(self, code: int = 1000) -> None:
        if not self.closed:
            self.closed = True
            try:
                self._send(OP_CLOSE, struct.pack("!H", code))
            except OSError:
                pass
        try:
            self._sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _read_http_head(sock: socket.socket) -> tuple[bytes, bytes]:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
        if len(data) > 1 << 16:
            raise WebSocketError("HTTP response head too large")
    head, _, rest = data.partition(b"\r\n\r\n")
    return head, rest


def _proxy_for(host: str) -> tuple[str, int, str | None] | None:
    """(proxy host, port, basic-auth) from HTTPS_PROXY, unless NO_PROXY covers the host."""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not proxy:
        return None
    if host in ("localhost", "127.0.0.1", "::1"):
        return None
    for entry in (os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or "").split(","):
        entry = entry.strip().lstrip("*")
        if entry and (host == entry.lstrip(".") or host.endswith("." + entry.lstrip("."))):
            return None
    parts = urlsplit(proxy if "://" in proxy else "http://" + proxy)
    auth = None
    if parts.username:
        auth = base64.b64encode(f"{parts.username}:{parts.password or ''}".encode()).decode()
    return parts.hostname, parts.port or 8080, auth


def connect(url: str, headers: dict[str, str] | None = None, timeout: float = 30.0) -> Connection:
    """Open a client connection to a ws:// or wss:// URL, sending `headers` with the upgrade."""
    parts = urlsplit(url)
    if parts.scheme not in ("ws", "wss"):
        raise ValueError(f"URL must start with ws:// or wss://, got {url!r}")
    host = parts.hostname
    secure = parts.scheme == "wss"
    port = parts.port or (443 if secure else 80)
    proxy = _proxy_for(host) if secure else None
    sock = socket.create_connection(proxy[:2] if proxy else (host, port), timeout=timeout)
    try:
        if proxy:
            req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
            if proxy[2]:
                req += f"Proxy-Authorization: Basic {proxy[2]}\r\n"
            sock.sendall((req + "\r\n").encode())
            head, _ = _read_http_head(sock)
            status = head.split(b" ", 2)[1:2]
            if status != [b"200"]:
                raise WebSocketError(f"proxy refused CONNECT to {host}:{port}: "
                                     f"{head.splitlines()[0].decode(errors='replace') if head else 'no reply'}",
                                     status=int(status[0]) if status and status[0].isdigit() else None)
        if secure:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode()
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        default_port = 443 if secure else 80
        lines = [f"GET {path} HTTP/1.1",
                 f"Host: {host}" + ("" if port == default_port else f":{port}"),
                 "Upgrade: websocket", "Connection: Upgrade",
                 f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
        lines += [f"{k}: {v}" for k, v in (headers or {}).items()]
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        head, rest = _read_http_head(sock)
        status_line = head.split(b"\r\n", 1)[0].decode(errors="replace")
        fields = {}
        for line in head.split(b"\r\n")[1:]:
            name, _, value = line.decode(errors="replace").partition(":")
            fields[name.strip().lower()] = value.strip()
        code = status_line.split(" ")[1] if len(status_line.split(" ")) > 1 else ""
        if code != "101":
            raise WebSocketError(f"WebSocket upgrade refused: {status_line}",
                                 status=int(code) if code.isdigit() else None,
                                 body=rest[:2000].decode(errors="replace"))
        if fields.get("sec-websocket-accept") != accept_key(key):
            raise WebSocketError("server sent a wrong Sec-WebSocket-Accept")
        return Connection(sock, is_client=True, leftover=rest)
    except BaseException:
        sock.close()
        raise


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        sock = self.request
        try:
            head, rest = _read_http_head(sock)
        except (OSError, WebSocketError):
            return
        lines = head.decode(errors="replace").split("\r\n")
        request_line = lines[0].split(" ")
        fields = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            fields[name.strip().lower()] = value.strip()
        path = request_line[1] if len(request_line) > 1 else "/"
        key = fields.get("sec-websocket-key")
        refusal = None if key else (400, "not a WebSocket upgrade")
        if refusal is None and self.server.authorize:
            refusal = self.server.authorize(path, fields)
        if refusal:
            code, message = refusal
            body = message.encode()
            sock.sendall(f"HTTP/1.1 {code} Refused\r\nContent-Type: text/plain\r\n"
                         f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
            return
        sock.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                      "Connection: Upgrade\r\n"
                      f"Sec-WebSocket-Accept: {accept_key(key)}\r\n\r\n").encode())
        conn = Connection(sock, is_client=False, leftover=rest)
        try:
            self.server.on_connect(conn, path, fields)
        except (ConnectionClosed, OSError):
            pass
        finally:
            conn.close()


class Server(socketserver.ThreadingTCPServer):
    """Threaded WebSocket server. `on_connect(conn, path, headers)` runs once per client;
    `authorize(path, headers)` may return (status, message) to refuse the upgrade."""
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, on_connect, host: str = "127.0.0.1", port: int = 0, authorize=None):
        self.on_connect = on_connect
        self.authorize = authorize
        super().__init__((host, port), _Handler)
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self.server_address[1]

    def start(self) -> "Server":
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
