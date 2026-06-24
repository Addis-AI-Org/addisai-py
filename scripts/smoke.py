"""Live smoke test against the real Addis AI API. Secret-gated; not a PR gate.

    ADDIS_API_KEY=<sandbox key> python scripts/smoke.py

Exits non-zero on any failure. Keep the surface small and cheap (one paid generate).
"""
import os
import sys
import time

from addisai import AddisAI

if not os.environ.get("ADDIS_API_KEY"):
    print("ADDIS_API_KEY not set — skipping smoke (no-op).")
    sys.exit(0)

addis = AddisAI()
failed = 0


def ok(m):
    print("  ✓", m)


def check(label, fn):
    global failed
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        failed += 1
        print("  ✗", label, "—", repr(e))


am = addis.voices.list(language="am")
ok(f"voices.list am={len(am)}") if am else check("voices.list", lambda: (_ for _ in ()).throw(Exception("empty")))
voice_id = next((v["id"] for v in am if v.get("is_default")), am[0]["id"] if am else "am-hiwot")


def _usage():
    u = addis.voice.usage()
    assert isinstance(u["balance"], (int, float))
    ok(f"usage {u['formatted_balance']}")


def _generate():
    clip = None
    for i in range(4):
        try:
            clip = addis.voice.generate(voice_id=voice_id, text="ሰላም", language="am")
            break
        except Exception as e:  # cold-start 503/504 tolerance
            if getattr(e, "status", None) in (503, 504) and i < 3:
                time.sleep(4)
                continue
            raise
    data = clip.content()
    assert len(data) > 0, "empty audio"
    ok(f"voice.generate {len(data)}B")


def _clips():
    n = 0
    for _c in addis.voice.clips.list(language="am", limit=1):
        n += 1
        break
    ok(f"clips iterated {n}")


def _chat():
    r = addis.chat.completions.create(language="am", messages=[{"role": "user", "content": "ሰላም በል"}])
    assert r["choices"][0]["message"]["content"], "empty"
    ok(f"chat \"{r['choices'][0]['message']['content'][:30]}\"")


def _translate():
    t = addis.translate.create(text="Hello", source="en", target="am")
    assert t["text"], "empty"
    ok(f"translate \"{t['text']}\"")


check("voice.usage", _usage)
check("voice.generate", _generate)
check("voice.clips.list", _clips)
check("chat", _chat)
check("translate", _translate)

print(f"\nSMOKE {'FAILED (' + str(failed) + ')' if failed else 'PASSED'}")
sys.exit(1 if failed else 0)
