"""OpenAI Realtime API over WebSocket.

Event names and shapes follow the Realtime API reference and guides at
developers.openai.com/api (read 2026-11-14); references/realtime-protocol.md lists exactly
which ones this adapter relies on. One exchange:

    connect  wss://api.openai.com/v1/realtime?model=<model>   (Authorization: Bearer <key>)
    <-  session.created
    ->  session.update      {session: {type: "realtime", output_modalities, audio: {...}}}
    <-  session.updated
    text:   ->  conversation.item.create  {item: message/user/[input_text]}
    audio:  ->  input_audio_buffer.append {audio: <base64 PCM16>}   (repeated)
            ->  input_audio_buffer.commit         <-  input_audio_buffer.committed
    ->  response.create
    <-  response.output_audio_transcript.delta / response.output_audio.delta /
        response.output_text.delta ... response.done

Turn detection is switched off so the client decides where the user turn ends: the clip is
the whole turn, and every arm ends its turn the same way.
"""
from __future__ import annotations

import base64
import copy
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import miniws  # noqa: E402

from .base import TargetInput, TargetResult  # noqa: E402

DEFAULT_URL = "wss://api.openai.com/v1/realtime"
PCM_FORMAT = {"type": "audio/pcm", "rate": 24000}
CHUNK_BYTES = 48000          # one second of PCM16 at 24 kHz per input_audio_buffer.append


def deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _websockets_connect(url: str, headers: dict, timeout: float):
    """Optional transport: the `websockets` package, for networks the built-in client does
    not cope with. Wrapped to the same send/recv/close surface as miniws.Connection."""
    from websockets.sync.client import connect as ws_connect

    class _Wrapped:
        def __init__(self):
            self._ws = ws_connect(url, additional_headers=headers, open_timeout=timeout,
                                  max_size=None)

        def send(self, text):
            self._ws.send(text)

        def recv(self):
            message = self._ws.recv(timeout=timeout)
            return message if isinstance(message, str) else message.decode(errors="replace")

        def close(self):
            self._ws.close()

    return _Wrapped()


class OpenAIRealtimeAdapter:
    name = "openai-realtime"

    def __init__(self, model: str, api_key: str | None = None, url: str | None = None,
                 output_modality: str = "audio", session: dict | None = None,
                 audio_input: str = "buffer", input_transcription_model: str | None = None,
                 max_output_tokens: int | None = None, timeout: float = 90.0,
                 transport: str = "stdlib"):
        if output_modality not in ("audio", "text"):
            raise ValueError("output_modality must be 'audio' or 'text'")
        if audio_input not in ("buffer", "item"):
            raise ValueError("audio_input must be 'buffer' or 'item'")
        if transport not in ("stdlib", "websockets"):
            raise ValueError("transport must be 'stdlib' or 'websockets'")
        self.model = model
        self.url = (url or DEFAULT_URL).rstrip("/")
        self._api_key = api_key
        self.output_modality = output_modality
        self.audio_input = audio_input
        self.timeout = timeout
        self.transport = transport
        audio_cfg: dict = {"input": {"format": dict(PCM_FORMAT), "turn_detection": None}}
        if output_modality == "audio":
            audio_cfg["output"] = {"format": dict(PCM_FORMAT)}
        if input_transcription_model:
            audio_cfg["input"]["transcription"] = {"model": input_transcription_model}
        base = {"type": "realtime", "output_modalities": [output_modality], "audio": audio_cfg}
        if max_output_tokens:
            base["max_output_tokens"] = max_output_tokens
        # The caller's session settings (instructions, tools, voice, reasoning...) are merged
        # in, but the keys that define the measurement stay as set above.
        merged = deep_merge(session or {}, base)
        self.session = merged

    def describe(self) -> dict:
        return {"adapter": self.name, "url": self.url, "model": self.model,
                "transport": self.transport, "output_modality": self.output_modality,
                "audio_input": self.audio_input, "session": self.session,
                "turn_detection": "off (client commits the audio buffer)",
                "session_per_case": True}

    # --- wire helpers ---------------------------------------------------------------------

    def _connect(self):
        sep = "&" if "?" in self.url else "?"
        url = f"{self.url}{sep}model={self.model}"
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        if self.transport == "websockets":
            return _websockets_connect(url, headers, self.timeout)
        conn = miniws.connect(url, headers=headers, timeout=self.timeout)
        return conn

    @staticmethod
    def _send(conn, event: dict) -> None:
        conn.send(json.dumps(event))

    @staticmethod
    def _error_text(event: dict) -> str:
        err = event.get("error") or {}
        return f"{err.get('type', 'error')}/{err.get('code')}: {err.get('message')}"

    def _wait_for(self, conn, wanted: str, result: TargetResult) -> dict:
        """Read events until `wanted` arrives. An `error` event ends the exchange."""
        while True:
            event = json.loads(conn.recv())
            result.events += 1
            kind = event.get("type")
            if kind == "error":
                raise RuntimeError(self._error_text(event))
            if kind == wanted:
                return event

    def _send_input(self, conn, item: TargetInput, result: TargetResult) -> None:
        if item.modality == "text":
            self._send(conn, {"type": "conversation.item.create", "item": {
                "type": "message", "role": "user",
                "content": [{"type": "input_text", "text": item.text}]}})
            return
        if item.rate != PCM_FORMAT["rate"]:
            raise ValueError(f"audio must be {PCM_FORMAT['rate']} Hz PCM16, got {item.rate} Hz")
        pcm = item.pcm or b""
        if self.audio_input == "item":
            self._send(conn, {"type": "conversation.item.create", "item": {
                "type": "message", "role": "user",
                "content": [{"type": "input_audio",
                             "audio": base64.b64encode(pcm).decode("ascii")}]}})
            return
        for start in range(0, len(pcm), CHUNK_BYTES):
            self._send(conn, {"type": "input_audio_buffer.append",
                              "audio": base64.b64encode(pcm[start:start + CHUNK_BYTES]).decode("ascii")})
        self._send(conn, {"type": "input_audio_buffer.commit"})
        self._wait_for(conn, "input_audio_buffer.committed", result)

    def _collect(self, conn, result: TargetResult) -> None:
        """Read the response stream into `result` until response.done."""
        said: list[str] = []        # transcript of spoken output, from deltas
        wrote: list[str] = []       # text output, from deltas
        finals: list[str] = []      # the *.done values, preferred over joined deltas
        audio_out = bytearray()
        while True:
            event = json.loads(conn.recv())
            result.events += 1
            kind = event.get("type")
            if kind == "error":
                raise RuntimeError(self._error_text(event))
            if kind == "response.output_audio.delta":
                audio_out += base64.b64decode(event.get("delta") or "")
            elif kind == "response.output_audio_transcript.delta":
                said.append(event.get("delta") or "")
            elif kind == "response.output_text.delta":
                wrote.append(event.get("delta") or "")
            elif kind == "response.output_audio_transcript.done":
                finals.append(event.get("transcript") or "")
            elif kind == "response.output_text.done":
                finals.append(event.get("text") or "")
            elif kind == "conversation.item.input_audio_transcription.completed":
                result.input_transcript = event.get("transcript")
            elif kind == "response.done":
                response = event.get("response") or {}
                result.status = response.get("status")
                details = response.get("status_details") or {}
                result.status_reason = details.get("reason") or (details.get("error") or {}).get("code")
                result.usage = response.get("usage") or {}
                from_done: list[str] = []
                for out in response.get("output") or []:
                    if out.get("type") == "function_call":
                        result.tool_calls.append({"name": out.get("name"),
                                                  "arguments": out.get("arguments")})
                    for part in out.get("content") or []:
                        text = part.get("transcript") or part.get("text")
                        if text:
                            from_done.append(text)
                result.transcript = (" ".join(from_done) or " ".join(t for t in finals if t)
                                     or "".join(said) or "".join(wrote)).strip()
                result.output_audio = bytes(audio_out)
                return

    # --- the one public call ----------------------------------------------------------------

    def respond(self, item: TargetInput) -> TargetResult:
        result = TargetResult()
        started = time.monotonic()
        conn = None
        try:
            conn = self._connect()
            created = self._wait_for(conn, "session.created", result)
            result.session_model = (created.get("session") or {}).get("model")
            self._send(conn, {"type": "session.update", "session": self.session})
            self._wait_for(conn, "session.updated", result)
            self._send_input(conn, item, result)
            self._send(conn, {"type": "response.create"})
            self._collect(conn, result)
        except miniws.WebSocketError as exc:
            status = f" (HTTP {exc.status})" if exc.status else ""
            result.error = f"websocket{status}: {exc}"
        except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
            result.error = f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001 - one failed case must not stop the run
            result.error = f"{type(exc).__name__}: {exc}"
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
        result.latency_s = round(time.monotonic() - started, 3)
        return result
