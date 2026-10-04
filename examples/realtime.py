"""Run with ADDIS_API_KEY and a complete sentence as the first argument."""
import os
import sys
from addisai import AddisAI

if len(sys.argv) != 2:
    raise SystemExit('Usage: python examples/realtime.py "A complete sentence to speak"')

with AddisAI() as addis:
    with addis.realtime.connect(voice_id=os.getenv("ADDIS_VOICE_ID", "am-hamen"),
                                language=os.getenv("ADDIS_VOICE_LANGUAGE", "am")) as connection:
        with open("realtime-speech.mp3", "wb") as output:
            for chunk in connection.speak(sys.argv[1]):
                output.write(chunk)
        print(connection.last_completion["usage"])
