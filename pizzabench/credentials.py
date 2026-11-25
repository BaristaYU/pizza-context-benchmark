"""Read user-managed provider keys. Values never enter reports, errors or logs."""

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = ROOT / "configs" / "api_keys.local.json"

PROVIDERS = ("gemini", "openai", "anthropic", "mistral", "vllm")
ENVIRONMENT = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
               "mistral": "MISTRAL_API_KEY",
               "vllm": "VLLM_API_KEY"}
# A key file may name a provider by service, by model family or by environment variable.
ALIASES = {"gemini": ("gemini", "google", "GEMINI_API_KEY", "GOOGLE_API_KEY"),
           "openai": ("openai", "gpt", "OPENAI_API_KEY", "GPT_API_KEY"),
           "anthropic": ("anthropic", "claude", "ANTHROPIC_API_KEY", "CLAUDE_API_KEY"),
           "mistral": ("mistral", "MISTRAL_API_KEY"),
           "vllm": ("vllm", "VLLM_API_KEY")}


class CredentialError(ValueError):
    """Raised with guidance only; the message never contains a key value."""


def read_key_file(path=None):
    path = Path(path) if path is not None else KEY_FILE
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        raise CredentialError(f"API 키 파일을 읽지 못했습니다: {path}") from None
    try:
        data = json.loads(text)
    except ValueError:
        raise CredentialError(f"API 키 파일의 JSON 형식이 잘못되었습니다: {path}") from None
    if not isinstance(data, dict) or any(not isinstance(value, str) for value in data.values()):
        raise CredentialError("API 키 파일은 객체이며 각 값은 문자열이어야 합니다")
    return data


def load_api_keys(path=None, *, required=(), use_environment=True):
    """Environment variables take priority over the key file.

    A missing file counts as empty so environment-only setups work; a key that is still
    missing afterwards is reported together with the file that was checked.
    """
    path = Path(path) if path is not None else KEY_FILE
    data = read_key_file(path) if path.exists() else {}
    keys = {}
    for provider in PROVIDERS:
        value = os.environ.get(ENVIRONMENT[provider], "").strip() if use_environment else ""
        if not value:
            for alias in ALIASES[provider]:
                value = str(data.get(alias, "")).strip()
                if value:
                    break
        keys[provider] = value
    missing = [provider for provider in required if not keys.get(provider)]
    if missing:
        raise CredentialError("다음 서비스의 키가 비어 있습니다: " + ", ".join(missing)
                              + f". {ENVIRONMENT[missing[0]]} 환경변수나 키 파일({path})을 확인하세요.")
    return keys


def key_status(path=None):
    """Report only whether a key is present, for screens and logs."""
    try:
        keys = load_api_keys(path)
    except CredentialError:
        return {provider: False for provider in PROVIDERS}
    return {provider: bool(value) for provider, value in keys.items()}
