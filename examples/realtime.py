"""Run with ADDIS_API_KEY and a complete sentence as the first argument."""
import os
import sys
from addisai import AddisAI

if len(sys.argv) != 2:
    raise SystemExit('Usage: python examples/realtime.py "A complete sentence to speak"')

with AddisAI() as addis:
    language = os.getenv("ADDIS_VOICE_LANGUAGE", "am")
    voice_id = os.getenv("ADDIS_VOICE_ID")
    if not voice_id:
        voices = [voice for voice in addis.voices.list(language=language)
                  if voice.get("is_available")]
        selected = next((voice for voice in voices if voice.get("is_default")),
                        voices[0] if voices else None)
        if selected is None:
            raise SystemExit("No available voice for language {}.".format(language))
        voice_id = selected["id"]
    with addis.realtime.connect(voice_id=voice_id, language=language) as connection:
        with open("realtime-speech.mp3", "wb") as output:
            for chunk in connection.speak(sys.argv[1]):
                output.write(chunk)
        print(connection.last_completion["usage"])
