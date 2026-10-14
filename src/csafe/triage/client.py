"""Gemini extraction client with a Gemma fallback and an offline fake for tests.

Keys come from the environment (or a .env file): GEMINI_API_KEY. Model names are configurable because
Google renames models often: GEMINI_MODEL (default below) and FALLBACK_MODEL. Check AI Studio for the
current names if a call fails with "model not found".
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Callable

from .prompt import CCTV_SYSTEM, SYSTEM
from .schema import Extract

# Flash-Lite: ~1.6 s median and 28/30 correct in our live test; Flash took ~29 s per call (too slow for 112)
DEFAULT_MODEL = "gemini-flash-lite-latest"
# Flash-Lite is the main model (fits a free key). Flash is only a backup, and is the first thing to run out of free quota.
# Models Google has retired (404) are skipped instantly, but there is no point listing them.
# "auto": at startup, look up which models this key can use and fall back to models with their OWN free quota:
# other Flash-Lite versions first, then Gemma (much larger free daily allowance), and Flash last (its free quota is tiny).
DEFAULT_FALLBACKS = "auto"


def load_env(path: str = ".env") -> None:
    """Minimal .env reader (KEY=value lines); does not override variables already set."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def parse_json(text: str) -> dict:
    """JSON from a model reply, tolerating ```json fences or text around it."""
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in reply")
    return json.loads(m.group(0))


class GeminiTriage:
    """extract(transcript, image=..., audio=...) -> (Extract, meta). Retries on rate limits, then falls back."""

    def __init__(self, api_key: str | None = None, model: str | None = None, fallback: str | None = None,
                 max_retries: int = 4, budget_s: float | None = None, request_timeout_s: float | None = None, _client=None):
        """budget_s: give up on Gemini after this long in total (the live app uses ~10 s, then the keyword
        fallback answers, so a 112 call never hangs). request_timeout_s: cut off a single slow request; must be
        >= 10 s, because the SDK forwards it to Google as a server deadline and shorter ones are rejected (400)."""
        if _client is None:
            from google import genai
            from google.genai import types
            load_env()
            key = api_key or os.environ.get("GEMINI_API_KEY")
            if not key:
                raise RuntimeError("GEMINI_API_KEY not set (put it in .env)")
            if request_timeout_s:
                request_timeout_s = max(10.0, request_timeout_s)
            opts = types.HttpOptions(timeout=int(request_timeout_s * 1000)) if request_timeout_s else None
            _client = genai.Client(api_key=key, http_options=opts) if opts else genai.Client(api_key=key)
        self.budget_s = budget_s
        self.client = _client
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
        chain = fallback or os.environ.get("FALLBACK_MODELS") or os.environ.get("FALLBACK_MODEL") or DEFAULT_FALLBACKS
        self.fallbacks = self._discover() if chain.strip() == "auto" else [m.strip() for m in chain.split(",") if m.strip()]
        self.max_retries = max_retries
        self._variant: dict[str, int] = {}

    def _discover(self) -> list[str]:
        """Fallback chain from the models this key can actually call (names change as Google ships versions)."""
        try:
            names = []
            for m in self.client.models.list():
                n = m.name.split("/")[-1]
                acts = getattr(m, "supported_actions", None) or ["generateContent"]
                if "generateContent" in acts:
                    names.append(n)
        except Exception:  # noqa: BLE001
            return ["gemini-flash-latest"]
        skip = ("tts", "image", "live", "audio", "embedding", "preview-0", "exp", "latest", "robotics", "computer", "transcribe")
        ver = lambda n: [int(x) if x.isdigit() else 0 for x in re.findall(r"\d+", n)]  # noqa: E731
        lite = sorted([n for n in names if "flash-lite" in n and n != self.model and not any(k in n for k in skip)], key=ver, reverse=True)
        gemma = sorted([n for n in names if n.startswith("gemma") and n.endswith("-it")], key=ver, reverse=True)
        gemma = [g for g in gemma if "26b" in g or "27b" in g][:1] or gemma[:1]
        if self.model.endswith("-latest") and lite:
            lite = lite[1:]   # the newest version is what the "-latest" alias points to: same model, same quota
        chain = lite[:1] + gemma + ["gemini-flash-latest"]
        return list(dict.fromkeys(chain))

    def _contents(self, transcript, image, audio):
        from google.genai import types
        parts = []
        if transcript:
            parts.append(f"CALL TRANSCRIPT:\n{transcript}")
        for blob, mime in ((image, "image/jpeg"), (audio, "audio/wav")):
            if blob is not None:
                if isinstance(blob, tuple):          # (bytes, mime type) from an upload
                    data, mt = blob
                elif isinstance(blob, bytes):
                    data, mt = blob, mime
                else:
                    data, mt = Path(blob).read_bytes(), _mime(blob, mime)
                parts.append(types.Part.from_bytes(data=data, mime_type=mt))
        return parts

    def _call(self, model: str, contents, structured: bool, schema=Extract, system: str = SYSTEM) -> str:
        from google.genai import types
        Extract_ = schema  # noqa: N806
        if structured and not model.startswith("gemma"):
            kw = dict(system_instruction=system, temperature=0, response_mime_type="application/json")
            gen = self.client.models.generate_content
            # Google changes what each model alias accepts. Try the fastest request first and step down on a 400:
            # (1) schema + thinking off, (2) schema only, (3) JSON mode with the schema written into the prompt.
            schema_prompt = [f"Return one JSON object matching this schema:\n{json.dumps(Extract_.model_json_schema())}", *contents]
            variants = [
                lambda: gen(model=model, contents=contents, config=types.GenerateContentConfig(
                    **kw, response_schema=Extract_, thinking_config=types.ThinkingConfig(thinking_budget=0))),
                lambda: gen(model=model, contents=contents, config=types.GenerateContentConfig(**kw, response_schema=Extract_)),
                lambda: gen(model=model, contents=schema_prompt, config=types.GenerateContentConfig(**kw)),
            ]
            start = self._variant.get(model, 0)
            for i in range(start, len(variants)):
                try:
                    text = variants[i]().text
                    self._variant[model] = i       # remember what this model accepts
                    return text
                except Exception as e:  # noqa: BLE001
                    bad_request = "INVALID_ARGUMENT" in str(e) or "400" in str(e)[:40] or "thinking" in str(e).lower()
                    if not bad_request or i == len(variants) - 1:
                        raise
            raise RuntimeError("unreachable")
        # Gemma via the Gemini API: no system instruction or JSON mode, so put both in the prompt
        schema = json.dumps(Extract_.model_json_schema())
        prompt = [f"{system}\n\nJSON schema:\n{schema}\n\nReturn only one JSON object.", *contents]
        return self.client.models.generate_content(model=model, contents=prompt,
                                                   config=types.GenerateContentConfig(temperature=0)).text

    def extract(self, transcript: str | None = None, image=None, audio=None) -> tuple[Extract, dict]:
        return self._run(self._contents(transcript, image, audio), Extract, SYSTEM)

    def verify_frame(self, image, report: str | None = None):
        """CCTV frame -> CCTVCheck: does the camera confirm the call?"""
        from .schema import CCTVCheck
        text = f"REPORT TO CHECK:\n{report}" if report else "No report yet: describe any emergency visible."
        return self._run(self._contents(text, image, None), CCTVCheck, CCTV_SYSTEM)

    def write_advisory(self, facts: dict):
        """Waterlogging plan facts -> Advisory in English, Hindi, Punjabi and an SMS."""
        from .prompt import ADVISORY_SYSTEM
        from .schema import Advisory
        return self._run([f"FACTS (JSON):\n{json.dumps(facts, ensure_ascii=False)}"], Advisory, ADVISORY_SYSTEM)

    def _run(self, contents, schema, system):
        errors = []
        start = time.time()
        left = lambda: (self.budget_s - (time.time() - start)) if self.budget_s else float("inf")  # noqa: E731
        for model in [self.model, *self.fallbacks]:
            structured = not model.startswith("gemma")
            for attempt in range(self.max_retries):
                if left() <= 0:
                    raise RuntimeError(f"Gemini took longer than {self.budget_s:.0f} s: " + " | ".join(errors[-3:]))
                t0 = time.time()
                try:
                    raw = self._call(model, contents, structured, schema, system)
                    x = schema.model_validate(parse_json(raw))
                    return x, {"model": model, "latency_s": round(time.time() - start, 2), "call_s": round(time.time() - t0, 2),
                               "attempts": attempt + 1, "errors": errors}
                except Exception as e:  # noqa: BLE001 - record and retry/fall back on anything
                    msg = f"{model}: {type(e).__name__}: {str(e)[:160]}"
                    errors.append(msg)
                    if _is_transient(e) and attempt < self.max_retries - 1:
                        wait = min(30, 3 * 2 ** attempt, max(0.0, left() - 1))  # 3, 6, 12 s ... but never past the budget
                        if wait <= 0:
                            break
                        time.sleep(wait)
                        continue
                    break  # bad output, unknown model or repeated overload: try the next model
        raise RuntimeError("all models failed: " + " | ".join(errors))


class FakeTriage:
    """Offline stand-in with the same interface: returns whatever `fn(transcript)` gives."""

    def __init__(self, fn: Callable[[str], dict | Extract], frame_fn: Callable | None = None):
        self.fn = fn
        self.frame_fn = frame_fn

    def verify_frame(self, image, report: str | None = None):
        from .schema import CCTVCheck
        if self.frame_fn is None:
            raise RuntimeError("reading camera frames needs Gemini")
        out = self.frame_fn(image, report)
        return (out if isinstance(out, CCTVCheck) else CCTVCheck.model_validate(out)), {"model": "fake", "latency_s": 0.0}

    def write_advisory(self, facts: dict):
        raise RuntimeError("writing advisories needs Gemini")

    def extract(self, transcript: str | None = None, image=None, audio=None) -> tuple[Extract, dict]:
        t0 = time.time()
        out = self.fn(transcript or "")
        x = out if isinstance(out, Extract) else Extract.model_validate(out)
        return x, {"model": "fake", "latency_s": round(time.time() - t0, 4), "attempts": 1, "errors": []}


def _is_transient(e: Exception) -> bool:
    """Rate limits and temporary server trouble: worth waiting and retrying the same model."""
    s = f"{type(e).__name__} {e}".lower()
    return any(k in s for k in ("429", "resource_exhausted", "rate limit", "503", "unavailable", "overloaded",
                                "500", "internal", "504", "deadline", "timeout", "high demand"))


def _mime(path, default):
    ext = str(path).lower().rsplit(".", 1)[-1]
    return {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
            "mp3": "audio/mp3", "wav": "audio/wav", "ogg": "audio/ogg", "m4a": "audio/aac", "aac": "audio/aac"}.get(ext, default)
