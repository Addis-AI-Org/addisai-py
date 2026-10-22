"""Customers buy Addis AI models. Published docs, examples, comments and
docstrings must not name the third-party models or vendors underneath them."""
import ast
import io
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = re.compile(
    r"gemini|google|vertex|azure|microsoft|openai|whisper|\bgpt|chatgpt|claude|anthropic|"
    r"elevenlabs|indextts|pyannote|latentsync|\bflash\b|supabase|cloudflare",
    re.IGNORECASE,
)


def test_docs_and_examples_name_no_vendor():
    paths = [ROOT / "README.md", ROOT / "CHANGELOG.md", *sorted((ROOT / "examples").glob("*"))]
    for path in paths:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not VENDOR.search(line), f"{path.name}:{number}: {line}"


def test_comments_and_docstrings_name_no_vendor():
    for path in sorted((ROOT / "addisai").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                assert not VENDOR.search(token.string), f"{path.name}:{token.start[0]}: {token.string}"
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node) or ""
                assert not VENDOR.search(doc), f"{path.name}: {doc[:80]}"
