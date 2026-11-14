"""The interface every realtime target adapter implements.

An adapter owns one wire protocol. It is given one input (typed text, or a clip of mono
PCM16 audio at 24 kHz) and returns what the model replied. It must open a fresh session per
input, so no case can see another case's conversation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Protocol


@dataclass
class TargetInput:
    case_id: str
    modality: str                 # "text" or "audio"
    text: str | None = None       # the prompt, when modality is "text"
    pcm: bytes | None = None      # little-endian PCM16 mono at `rate`, when modality is "audio"
    rate: int = 24000


@dataclass
class TargetResult:
    transcript: str = ""                  # what the model said (audio transcript) or wrote
    status: str | None = None             # the provider's final response status
    status_reason: str | None = None      # why it did not complete, e.g. a content filter
    error: str | None = None              # set when the exchange failed; transcript is then unusable
    output_audio: bytes = b""             # PCM16 the model spoke, when the output is audio
    output_rate: int = 24000
    input_transcript: str | None = None   # provider-side transcription of the input, if enabled
    tool_calls: list = field(default_factory=list)   # [{name, arguments}] the model asked for
    usage: dict = field(default_factory=dict)        # token counts as the provider reports them
    session_model: str | None = None      # the model the provider says the session runs
    latency_s: float | None = None
    events: int = 0                       # server events received

    def to_row(self) -> dict:
        """Fields for samples.jsonl; the audio bytes are stored separately."""
        row = asdict(self)
        row["output_audio_seconds"] = round(len(self.output_audio) / 2 / self.output_rate, 3)
        del row["output_audio"]
        return row


class RealtimeAdapter(Protocol):
    name: str

    def describe(self) -> dict:
        """What was configured (endpoint, model, session settings) for the run manifest.
        Never includes a credential."""

    def respond(self, item: TargetInput) -> TargetResult:
        """Send one input in a fresh session and return the reply. Never raises for a
        target-side failure: it returns a result with `error` set."""
