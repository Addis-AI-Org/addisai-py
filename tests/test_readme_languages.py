"""The README's language table must list exactly the SDK's languages and voices, and never a retired voice."""
import pathlib
import re

from addisai import DEFAULT_VOICES, REALTIME_LANGUAGES, VOICE_LANGUAGES, VOICES

README = pathlib.Path(__file__).resolve().parents[1] / "README.md"
RETIRED = ("ha-hauwa",)


def table():
    text = README.read_text(encoding="utf-8")
    return text[text.index("<!-- languages:start -->"):text.index("<!-- languages:end -->")]


def rows():
    """The body rows (no header, no separator)."""
    return [line for line in table().splitlines() if line.startswith("| ") and "`" in line]


def test_table_has_one_row_per_language_in_order():
    codes = re.findall(r"^\| [^|]+ \| `([a-z]+)` \|", table(), re.M)
    assert tuple(codes) == VOICE_LANGUAGES


def test_table_lists_every_voice_default_first():
    by_code = {re.search(r"`([a-z]+)`", line).group(1): line for line in rows()}
    for language, voices in VOICES.items():
        ids = re.findall(r"`([a-z]+-[a-z0-9-]+)`", by_code[language].split("|")[3])
        assert ids[0] == DEFAULT_VOICES[language]
        if language != "am":  # Amharic shows its default and a count
            assert ids == list(voices)
        else:
            assert f"and {len(voices) - 1} more" in by_code[language]


def test_table_marks_streaming_languages():
    for line in rows():
        code = re.search(r"`([a-z]+)`", line).group(1)
        assert ("| yes |" in line) == (code in REALTIME_LANGUAGES), line


def test_no_retired_voice_anywhere_public():
    root = README.parent
    for path in [README, root / "CHANGELOG.md", *root.glob("examples/*"), *root.glob("addisai/**/*.py")]:
        text = path.read_text(encoding="utf-8")
        for voice in RETIRED:
            assert voice not in text, f"{voice} in {path}"
