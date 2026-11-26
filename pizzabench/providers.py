"""Gemini, OpenAI and Anthropic tool-calling adapters over the standard library.

Each session exposes the same two calls so the runner stays provider independent:
``ask(prompt, tools)`` returns the requested actions with token usage, and
``reply(results)`` returns the environment responses. Keys live only in headers.
"""

import json
import time
from copy import deepcopy
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROVIDERS = {"gemini": "Gemini", "openai": "OpenAI", "anthropic": "Anthropic",
             "mistral": "Mistral", "vllm": "vLLM 로컬 서버"}
ENDPOINTS = {"gemini": "https://generativelanguage.googleapis.com/v1beta",
             "openai": "https://api.openai.com/v1",
             "anthropic": "https://api.anthropic.com/v1",
             # OpenAI-compatible chat services carried over from main.
             "mistral": "https://api.mistral.ai/v1",
             # A vLLM server started by the user; the address comes from configs or --base-url.
             "vllm": "http://localhost:8000/v1"}
ANTHROPIC_VERSION = "2023-06-01"
REQUEST_TIMEOUT = 60
# Gemini accepts a subset of JSON Schema; unknown keywords are rejected outright.
GEMINI_SCHEMA_KEYS = {"type", "description", "enum", "items", "properties", "required",
                      "minimum", "maximum", "minItems", "maxItems", "nullable"}


class CancelledRequest(Exception):
    """Raised when a stop signal arrives before or during a request."""


class ProviderError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class RequestPacer:
    """Start-to-start interval shared by every request in one run; no retries."""

    def __init__(self, interval=3):
        if not 0 <= interval <= 300:
            raise ValueError("Request interval must be 0..300 seconds")
        self.interval = float(interval)
        self.last_started = None

    def wait(self, stop=None):
        stop = stop or Event()
        if stop.is_set():
            raise CancelledRequest()
        if self.last_started is not None:
            remaining = self.interval - (time.monotonic() - self.last_started)
            if remaining > 0 and stop.wait(remaining):
                raise CancelledRequest()
        if stop.is_set():
            raise CancelledRequest()
        self.last_started = time.monotonic()


def provider_message(exc):
    """Read the provider's own error text; request headers are never read back."""
    try:
        payload = json.loads(exc.read().decode("utf-8", "replace"))
    except Exception:
        return "Provider rejected request"
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])[:200]
    if isinstance(error, str):
        return error[:200]
    return "Provider rejected request"


def request_json(url, headers, body=None, *, method="POST", timeout=REQUEST_TIMEOUT):
    data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8") if body is not None else None
    request = Request(url, data=data, method=method,
                      headers={"Content-Type": "application/json", "User-Agent": "PizzaBench/1.0", **headers})
    try:
        with urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ProviderError(exc.code, provider_message(exc)) from None
    except (URLError, TimeoutError, ValueError):
        raise ProviderError(None, "Provider network or response error") from None
    if not isinstance(value, dict):
        raise ProviderError(None, "Invalid response object")
    if value.get("error"):
        error = value["error"]
        code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        raise ProviderError(code if isinstance(code, int) else None,
                            str(message or "Provider returned error")[:200])
    return value


def gemini_schema(value):
    """Keep the keywords Gemini documents and uppercase the type names it expects."""
    if not isinstance(value, dict):
        return value
    schema = {}
    for key, item in value.items():
        if key not in GEMINI_SCHEMA_KEYS:
            continue
        if key == "type" and isinstance(item, str):
            schema[key] = item.upper()
        elif key == "properties" and isinstance(item, dict):
            schema[key] = {name: gemini_schema(field) for name, field in item.items()}
        elif key == "items":
            schema[key] = gemini_schema(item)
        else:
            schema[key] = deepcopy(item)
    return schema


OPAQUE_FIELDS = {"signature", "thoughtSignature", "encrypted_content", "data"}


def readable(value):
    """The model's whole reply for monitoring, with encrypted or signed blobs shortened.

    Claude, Gemini and OpenAI return their reasoning only as summaries plus encrypted
    material that must be resent unchanged; that material cannot be read, so the record
    keeps its length instead of its bytes. Everything else is kept as returned.
    """
    if isinstance(value, list):
        return [readable(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {key: (f"<암호화된 값 {len(item)}자>" if key in OPAQUE_FIELDS and isinstance(item, str) else readable(item))
            for key, item in value.items()}


def usage_record(provider, raw):
    """Normalise token usage so cost and reports do not branch per provider."""
    raw = raw or {}
    if provider == "gemini":
        output = (raw.get("candidatesTokenCount") or 0) + (raw.get("thoughtsTokenCount") or 0)
        prompt = raw.get("promptTokenCount") or 0
        total = raw.get("totalTokenCount")
        return {"input": prompt, "output": output,
                "total": total if isinstance(total, int) else prompt + output, "raw": raw}
    if provider == "openai":
        return {"input": raw.get("input_tokens") or 0, "output": raw.get("output_tokens") or 0,
                "total": raw.get("total_tokens") or 0, "raw": raw}
    if provider == "chat":
        return {"input": raw.get("prompt_tokens") or 0, "output": raw.get("completion_tokens") or 0,
                "total": raw.get("total_tokens") or 0, "raw": raw}
    cached = (raw.get("cache_read_input_tokens") or 0) + (raw.get("cache_creation_input_tokens") or 0)
    received = (raw.get("input_tokens") or 0) + cached
    return {"input": received, "output": raw.get("output_tokens") or 0,
            "total": received + (raw.get("output_tokens") or 0), "raw": raw}


class GeminiSession:
    provider = "gemini"

    def __init__(self, key, model, *, timeout=REQUEST_TIMEOUT, reasoning_effort=None):
        self.key, self.model, self.timeout = key, model, timeout
        self.reasoning_effort = reasoning_effort
        self.history, self.pending, self.last_output = [], [], {}
        self.settings = {"provider": "Gemini", "api": "generateContent", "transport": "Python urllib",
                         "request_timeout_ms": timeout * 1000, "retry_attempts": 1,
                         "generation_parameters": "model defaults; function calling mode AUTO",
                         "reasoning_visibility": "thought summaries (includeThoughts)",
                         "reasoning_effort": reasoning_effort or "model default"}

    def url(self, action):
        return f"{ENDPOINTS['gemini']}/models/{self.model}:{action}"

    def declarations(self, tools):
        declarations = []
        for spec in tools:
            declaration = {"name": spec["name"], "description": spec.get("description", "")}
            parameters = spec.get("parameters") or {}
            if parameters.get("properties"):
                declaration["parameters"] = gemini_schema(parameters)
            declarations.append(declaration)
        return declarations

    def ask(self, prompt, tools):
        if not self.history:
            self.history.append({"role": "user", "parts": [{"text": prompt}]})
        body = {"contents": self.history,
                # Visibility only: thought summaries come back; the thinking itself is unchanged.
                "generationConfig": {"thinkingConfig": {"includeThoughts": True}}}
        if tools:
            body["tools"] = [{"functionDeclarations": self.declarations(tools)}]
            body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
        if self.reasoning_effort:
            body["generationConfig"]["thinkingConfig"]["thinkingLevel"] = self.reasoning_effort
        value = request_json(self.url("generateContent"), {"x-goog-api-key": self.key}, body, timeout=self.timeout)
        candidates = value.get("candidates") or []
        content = (candidates[0] or {}).get("content") if candidates else None
        if not content:
            raise ProviderError(None, "No model response")
        # Store the content exactly as returned so thought signatures survive the next turn.
        self.history.append(content)
        parts = content.get("parts") or []
        self.pending = [part["functionCall"] for part in parts if part.get("functionCall")]
        self.last_output = {"reasoning": "\n\n".join(p["text"] for p in parts if p.get("thought") and p.get("text")),
                            "text": "\n".join(p["text"] for p in parts if not p.get("thought") and p.get("text")),
                            "raw": readable(content), "reasoning_scope": "summary"}
        actions = [{"tool": call.get("name"), "args": dict(call.get("args") or {})} for call in self.pending]
        return actions, usage_record("gemini", value.get("usageMetadata"))

    def reply(self, results, idle=None):
        if not self.pending:
            self.history.append({"role": "user", "parts": [{"text": idle or "{}"}]})
            return
        parts = [{"functionResponse": {"name": call.get("name"), "response": result}}
                 for call, result in zip(self.pending, results)]
        self.history.append({"role": "user", "parts": parts})

    def count_tokens(self, prompt, tools):
        # countTokens accepts tools only inside a full generateContentRequest.
        request = {"model": f"models/{self.model}", "contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if tools:
            request["tools"] = [{"functionDeclarations": self.declarations(tools)}]
        body = {"generateContentRequest": request}
        value = request_json(self.url("countTokens"), {"x-goog-api-key": self.key}, body, timeout=self.timeout)
        return int(value.get("totalTokens") or 0)

    def close(self):
        self.key = ""


class ChatSession:
    """Chat Completions, used by the OpenAI-compatible services and by vLLM."""

    provider = None

    def __init__(self, key, model, *, timeout=REQUEST_TIMEOUT, max_output_tokens=None):
        self.key, self.model, self.timeout = key, model, timeout
        self.max_output_tokens = max_output_tokens
        self.base_url = ENDPOINTS[self.provider]
        self.history, self.pending, self.last_output = [], [], {}
        self.settings = {"provider": PROVIDERS[self.provider], "api": "chat/completions", "transport": "Python urllib",
                         "request_timeout_ms": timeout * 1000, "retry_attempts": 1,
                         "generation_parameters": "model defaults; parallel_tool_calls=true"}

    reasoning_fields = ()

    def headers(self):
        return {"Authorization": "Bearer " + self.key}

    def extra_body(self):
        return {}

    def declarations(self, tools):
        return [{"type": "function",
                 "function": {"name": spec["name"], "description": spec.get("description", ""),
                              "parameters": spec.get("parameters") or {"type": "object", "properties": {}}}}
                for spec in tools]

    def ask(self, prompt, tools):
        if not self.history:
            self.history.append({"role": "user", "content": prompt})
        body = {"model": self.model, "messages": self.history, "stream": False}
        if tools:
            body.update(tools=self.declarations(tools), tool_choice="auto", parallel_tool_calls=True)
        if self.max_output_tokens:
            body["max_completion_tokens"] = self.max_output_tokens
        body.update(self.extra_body())
        value = request_json(self.base_url + "/chat/completions", self.headers(), body, timeout=self.timeout)
        choices = value.get("choices") or []
        if not choices:
            raise ProviderError(None, "No model response")
        message = dict(choices[0].get("message") or {})
        calls = message.get("tool_calls") or []
        entry = {"role": "assistant", "content": message.get("content")}
        reasoning = next((message[field] for field in ("reasoning_content", "reasoning") if message.get(field)), "")
        for field in self.reasoning_fields:
            if message.get(field):
                entry[field] = message[field]
        self.last_output = {"reasoning": reasoning if isinstance(reasoning, str) else "",
                            "text": message.get("content") or "", "raw": readable(message),
                            "reasoning_scope": "full" if self.provider == "vllm" else "summary"}
        if calls:
            entry["tool_calls"] = calls
        self.history.append(entry)
        self.pending = calls
        actions = []
        for call in calls:
            function = call.get("function") or {}
            arguments = function.get("arguments")
            try:
                parsed = json.loads(arguments) if isinstance(arguments, str) and arguments else {}
            except ValueError:
                parsed = None
            actions.append({"tool": function.get("name"), "args": parsed})
        return actions, usage_record("chat", value.get("usage"))

    def reply(self, results, idle=None):
        if not self.pending:
            self.history.append({"role": "user", "content": idle or "{}"})
            return
        for call, result in zip(self.pending, results):
            self.history.append({"role": "tool", "tool_call_id": call.get("id"),
                                 "content": json.dumps(result, ensure_ascii=False)})

    def close(self):
        self.key = ""


class OpenAISession:
    """OpenAI Responses API.

    With ``store: false`` the service keeps nothing, so each request resends the whole
    input. Reasoning items come back encrypted and are resent unchanged, which keeps the
    model's reasoning across tool turns as Claude's thinking blocks and Gemini's thought
    signatures do. Reasoning summaries are requested for monitoring; they do not change
    the reasoning itself.
    """

    provider = "openai"
    REASONING_PREFIXES = ("gpt-5", "gpt-6", "o1", "o3", "o4")

    def __init__(self, key, model, *, timeout=REQUEST_TIMEOUT, max_output_tokens=None, reasoning_effort=None):
        self.key, self.model, self.timeout = key, model, timeout
        self.max_output_tokens = max_output_tokens
        self.reasoning_effort = reasoning_effort
        self.reasoning = str(model).startswith(self.REASONING_PREFIXES)
        self.history, self.pending, self.last_output = [], [], {}
        self.settings = {"provider": "OpenAI", "api": "responses", "transport": "Python urllib",
                         "request_timeout_ms": timeout * 1000, "retry_attempts": 1,
                         "generation_parameters": "model defaults; parallel_tool_calls=true; store=false",
                         "reasoning_visibility": "summary auto, encrypted reasoning resent" if self.reasoning else "none",
                         "reasoning_effort": reasoning_effort or "model default"}

    def declarations(self, tools):
        return [{"type": "function", "name": spec["name"], "description": spec.get("description", ""),
                 "parameters": spec.get("parameters") or {"type": "object", "properties": {}}}
                for spec in tools]

    def ask(self, prompt, tools):
        if not self.history:
            self.history.append({"role": "user", "content": prompt})
        body = {"model": self.model, "input": self.history, "store": False}
        if tools:
            body.update(tools=self.declarations(tools), tool_choice="auto", parallel_tool_calls=True)
        if self.reasoning:
            body["reasoning"] = {"summary": "auto"}
            if self.reasoning_effort:
                body["reasoning"]["effort"] = self.reasoning_effort
            body["include"] = ["reasoning.encrypted_content"]
        if self.max_output_tokens:
            body["max_output_tokens"] = self.max_output_tokens
        value = request_json(ENDPOINTS["openai"] + "/responses", {"Authorization": "Bearer " + self.key},
                             body, timeout=self.timeout)
        output = value.get("output")
        if not isinstance(output, list):
            raise ProviderError(None, "No model response")
        self.history.extend(output)
        self.pending = [item for item in output if item.get("type") == "function_call"]
        summaries = [part.get("text", "") for item in output if item.get("type") == "reasoning"
                     for part in item.get("summary") or []]
        texts = [part.get("text", "") for item in output if item.get("type") == "message"
                 for part in item.get("content") or [] if part.get("type") == "output_text"]
        self.last_output = {"reasoning": "\n\n".join(s for s in summaries if s),
                            "text": "\n".join(s for s in texts if s), "raw": readable(output),
                            "reasoning_scope": "summary"}
        actions = []
        for call in self.pending:
            arguments = call.get("arguments")
            try:
                parsed = json.loads(arguments) if isinstance(arguments, str) and arguments else {}
            except ValueError:
                parsed = None
            actions.append({"tool": call.get("name"), "args": parsed})
        return actions, usage_record("openai", value.get("usage"))

    def reply(self, results, idle=None):
        if not self.pending:
            self.history.append({"role": "user", "content": idle or "{}"})
            return
        for call, result in zip(self.pending, results):
            self.history.append({"type": "function_call_output", "call_id": call.get("call_id"),
                                 "output": json.dumps(result, ensure_ascii=False)})

    def close(self):
        self.key = ""


class MistralSession(ChatSession):
    """Mistral's free Experiment plan can run the benchmark: 1 request per second and a
    monthly token allowance. Groq and OpenRouter were removed because their free daily
    limits cannot finish one benchmark run."""

    provider = "mistral"


class VLLMSession(ChatSession):
    """A local model behind vLLM's OpenAI-compatible server.

    Sampling and chat-template options come from the model's card and are sent
    explicitly, so the record shows the values the server used. The reasoning text vLLM
    returns is kept in the assistant message, which lets templates such as Qwen3.6's
    ``preserve_thinking`` show it again on later turns.
    """

    provider = "vllm"
    reasoning_fields = ("reasoning_content", "reasoning")

    def __init__(self, key, model, *, base_url=None, sampling=None, chat_template_kwargs=None, **options):
        super().__init__(key, model, **options)
        self.base_url = (base_url or ENDPOINTS["vllm"]).rstrip("/")
        self.sampling = dict(sampling or {})
        self.chat_template_kwargs = dict(chat_template_kwargs or {})
        self.settings.update(api="chat/completions (vLLM)", base_url=self.base_url, sampling=self.sampling,
                             chat_template_kwargs=self.chat_template_kwargs,
                             generation_parameters="model card sampling; parallel_tool_calls=true")

    def headers(self):
        return {"Authorization": "Bearer " + self.key} if self.key else {}

    def extra_body(self):
        body = dict(self.sampling)
        if self.chat_template_kwargs:
            body["chat_template_kwargs"] = self.chat_template_kwargs
        return body


class AnthropicSession:
    provider = "anthropic"

    def __init__(self, key, model, *, timeout=REQUEST_TIMEOUT, max_output_tokens=8192, effort=None,
                 reasoning_effort=None):
        self.key, self.model, self.timeout = key, model, timeout
        self.max_output_tokens = max_output_tokens
        self.effort = effort = effort or reasoning_effort
        self.history, self.pending = [], []
        self.settings = {"provider": "Anthropic", "api": "messages", "transport": "Python urllib",
                         "anthropic_version": ANTHROPIC_VERSION, "request_timeout_ms": timeout * 1000,
                         "retry_attempts": 1, "max_tokens": max_output_tokens,
                         "generation_parameters": "model defaults" + (f"; effort={effort}" if effort else ""),
                         "reasoning_visibility": "thinking display summarized",
                         "reasoning_effort": effort or "model default"}
        self.last_output = {}

    def headers(self):
        return {"x-api-key": self.key, "anthropic-version": ANTHROPIC_VERSION}

    def declarations(self, tools):
        return [{"name": spec["name"], "description": spec.get("description", ""),
                 "input_schema": spec.get("parameters") or {"type": "object", "properties": {}}}
                for spec in tools]

    def ask(self, prompt, tools):
        if not self.history:
            self.history.append({"role": "user", "content": prompt})
        body = {"model": self.model, "max_tokens": self.max_output_tokens, "messages": self.history,
                # Visibility only: summaries instead of empty thinking text; thinking is unchanged.
                "thinking": {"type": "adaptive", "display": "summarized"}}
        if tools:
            body.update(tools=self.declarations(tools), tool_choice={"type": "auto"})
        if self.effort:
            body["output_config"] = {"effort": self.effort}
        value = request_json(ENDPOINTS["anthropic"] + "/messages", self.headers(), body, timeout=self.timeout)
        content = value.get("content")
        if not isinstance(content, list):
            raise ProviderError(None, "No model response")
        if value.get("stop_reason") == "refusal":
            raise ProviderError(None, "Model declined the request (stop_reason=refusal)")
        # Thinking blocks must return unchanged on the next request, so keep the content as sent.
        self.history.append({"role": "assistant", "content": content})
        self.pending = [block for block in content if block.get("type") == "tool_use"]
        self.last_output = {"reasoning": "\n\n".join(b.get("thinking", "") for b in content
                                                       if b.get("type") == "thinking" and b.get("thinking")),
                            "text": "\n".join(b.get("text", "") for b in content if b.get("type") == "text"),
                            "raw": readable(content), "reasoning_scope": "summary"}
        actions = [{"tool": block.get("name"), "args": dict(block.get("input") or {})} for block in self.pending]
        return actions, usage_record("anthropic", value.get("usage"))

    def reply(self, results, idle=None):
        if not self.pending:
            self.history.append({"role": "user", "content": idle or "{}"})
            return
        blocks = [{"type": "tool_result", "tool_use_id": call.get("id"),
                   "content": json.dumps(result, ensure_ascii=False)}
                  for call, result in zip(self.pending, results)]
        self.history.append({"role": "user", "content": blocks})

    def count_tokens(self, prompt, tools):
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt}]}
        if tools:
            body["tools"] = self.declarations(tools)
        value = request_json(ENDPOINTS["anthropic"] + "/messages/count_tokens", self.headers(),
                             body, timeout=self.timeout)
        return int(value.get("input_tokens") or 0)

    def close(self):
        self.key = ""


class PacedSession:
    """Applies the shared request interval and stop signal to every model call."""

    def __init__(self, session, pacer, stop=None):
        self.session, self.pacer, self.stop = session, pacer, stop
        self.provider = session.provider
        self.model = session.model
        self.settings = {**session.settings, "request_interval_seconds": pacer.interval}

    def ask(self, prompt, tools):
        self.pacer.wait(self.stop)
        return self.session.ask(prompt, tools)

    @property
    def last_output(self):
        return getattr(self.session, "last_output", {}) or {}

    def reply(self, results, idle=None):
        self.session.reply(results, idle=idle)

    def count_tokens(self, prompt, tools):
        counter = getattr(self.session, "count_tokens", None)
        if counter is None:
            raise ProviderError(None, "This provider has no token counting endpoint")
        self.pacer.wait(self.stop)
        return counter(prompt, tools)

    def close(self):
        self.session.close()


SESSIONS = {"gemini": GeminiSession, "openai": OpenAISession, "anthropic": AnthropicSession,
            "mistral": MistralSession, "vllm": VLLMSession}
KEYLESS = {"vllm"}


def create_session(provider, key, model, *, pacer=None, stop=None, **options):
    if provider not in SESSIONS:
        raise ValueError(f"Unsupported provider: {provider}")
    if not key and provider not in KEYLESS:
        raise ValueError(f"No API key for {provider}")
    return PacedSession(SESSIONS[provider](key, model, **options), pacer or RequestPacer(3), stop)


def list_models(provider, key, *, timeout=REQUEST_TIMEOUT, base_url=None):
    """Read the account's available models. This call does not consume tokens."""
    if provider == "vllm":
        headers = {"Authorization": "Bearer " + key} if key else {}
        value = request_json((base_url or ENDPOINTS["vllm"]).rstrip("/") + "/models", headers,
                             method="GET", timeout=timeout)
        return sorted(model["id"] for model in value.get("data") or [] if isinstance(model.get("id"), str))
    if provider == "gemini":
        value = request_json(f"{ENDPOINTS['gemini']}/models?pageSize=200", {"x-goog-api-key": key},
                             method="GET", timeout=timeout)
        return sorted(model["name"].removeprefix("models/") for model in value.get("models") or []
                      if "generateContent" in (model.get("supportedGenerationMethods") or []))
    if provider in {"openai", "mistral"}:
        value = request_json(ENDPOINTS[provider] + "/models", {"Authorization": "Bearer " + key},
                             method="GET", timeout=timeout)
        return sorted(model["id"] for model in value.get("data") or [] if isinstance(model.get("id"), str))
    if provider == "anthropic":
        value = request_json(ENDPOINTS["anthropic"] + "/models?limit=100",
                             {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION},
                             method="GET", timeout=timeout)
        return [model["id"] for model in value.get("data") or []]
    raise ValueError(f"Unsupported provider: {provider}")
