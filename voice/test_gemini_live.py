"""Standalone Gemini Live (native audio) smoke test — no telephony involved.

Verifies that GEMINI_API_KEY can open a Live session against the native-audio
model, send a turn, and receive at least one audio + text response chunk. This
isolates the Gemini half of the bridge so a failing real call can be diagnosed.

Run:
    python test_gemini_live.py

Exits 0 on success (printing how many audio bytes / what text came back).
"""
from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

# The native-audio Live model. Override with GEMINI_LIVE_MODEL if Google rotates it.
MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")

SYSTEM = (
    "You are phoning Alex on behalf of an autonomous buyer agent. Pending decision: "
    "the seller wants 340 EUR for a ThinkPad, 20 EUR over the 320 cap. Briefly explain "
    "it and ask whether to approve, counter, or decline. Keep it to one short sentence."
)


async def run() -> int:
    load_dotenv()
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not set", file=sys.stderr)
        return 2

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})

    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=types.Content(parts=[types.Part(text=SYSTEM)]),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )

    audio_bytes = 0
    text_out = ""
    try:
        async with client.aio.live.connect(model=MODEL, config=config) as session:
            print(f"[gemini] connected to {MODEL}")
            # Kick the model with a text turn (telephony path sends audio instead).
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(text="Hi, why are you calling?")]),
                turn_complete=True,
            )
            async for response in session.receive():
                sc = response.server_content
                if sc is None:
                    continue
                if sc.model_turn:
                    for part in sc.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            audio_bytes += len(part.inline_data.data)
                        if part.text:
                            text_out += part.text
                if sc.output_transcription and sc.output_transcription.text:
                    text_out += sc.output_transcription.text
                if sc.turn_complete:
                    break
    except Exception as e:  # noqa: BLE001
        print(f"[gemini] FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(f"[gemini] audio bytes received: {audio_bytes}")
    print(f"[gemini] transcript/text: {text_out.strip()[:300]!r}")
    ok = audio_bytes > 0 or bool(text_out.strip())
    print("[gemini] RESULT:", "PASS" if ok else "FAIL (no audio/text returned)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
