"""Sovereign mode: Gemma, Google's open-weight model, running on the control room's own computer through Ollama.

No call text, photo or camera frame leaves the machine. Same interface as GeminiTriage
(extract / verify_frame / write_advisory -> (pydantic object, meta)), so the app and the evaluation can swap
one for the other.

Setup on the computer that runs OpenHand:
    1. install Ollama (https://ollama.com)
    2. ollama pull gemma3:4b          # ~3.3 GB; reads text and images. gemma3:12b is more accurate if you have 16 GB+
    3. in .env:  LOCAL_MODEL=gemma3:4b   (optional; this is the default)
                 TRIAGE_ENGINE=local     (optional: start in sovereign mode; you can also switch in the app)

Voice clips are not supported locally yet (Gemma 3 in Ollama reads text and images, not audio): a call with
audio needs Gemini, or a local speech-to-text step in front of this.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from .client import load_env, parse_json
from .prompt import CCTV_SYSTEM, SYSTEM
from .schema import Extract

DEFAULT_LOCAL_MODEL = "gemma3:4b"
DEFAULT_HOST = "http://localhost:11434"


def _b64(blob) -> str:
    if isinstance(blob, tuple):
        blob = blob[0]
    if not isinstance(blob, (bytes, bytearray)):
        blob = Path(blob).read_bytes()
    return base64.b64encode(blob).decode()


class LocalGemmaTriage:
    """extract(transcript, image=...) -> (Extract, meta), answered by a Gemma model on this computer."""

    engine = "local"

    def __init__(self, model: str | None = None, host: str | None = None, timeout_s: float = 120.0, retries: int = 1, _post=None):
        load_env()
        self.model = model or os.environ.get("LOCAL_MODEL", DEFAULT_LOCAL_MODEL)
        self.host = (host or os.environ.get("OLLAMA_HOST_URL") or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).rstrip("/")
        if not self.host.startswith("http"):
            self.host = "http://" + self.host
        self.timeout_s = timeout_s
        self.retries = retries
        self.fallbacks: list[str] = []          # nothing outside this computer to fall back to, by design
        self._post = _post or self._http_post

    # ---- plumbing ----
    def _http_post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(self.host + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as r:  # noqa: S310 - local Ollama server
            return json.loads(r.read().decode())

    def status(self) -> dict:
        """Is Ollama running here, and has the model been downloaded?"""
        try:
            req = urllib.request.Request(self.host + "/api/tags")
            with urllib.request.urlopen(req, timeout=3) as r:  # noqa: S310
                names = [m.get("name", "") for m in json.loads(r.read().decode()).get("models", [])]
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "model": self.model, "host": self.host,
                    "reason": f"Ollama is not running at {self.host} ({type(e).__name__}). Install it from ollama.com and open it."}
        want = self.model if ":" in self.model else self.model + ":latest"
        if want not in names and self.model not in names:
            return {"ok": False, "model": self.model, "host": self.host, "installed": names,
                    "reason": f"Ollama is running but {self.model} isn't downloaded. Run: ollama pull {self.model}"}
        return {"ok": True, "model": self.model, "host": self.host, "installed": names}

    def _chat(self, system: str, text: str, schema, images: list[str] | None = None) -> str:
        user = {"role": "user", "content": text}
        if images:
            user["images"] = images
        body = {"model": self.model, "stream": False, "keep_alive": "30m",
                "options": {"temperature": 0, "num_ctx": 8192},
                "messages": [{"role": "system", "content": f"{system}\n\nReturn only one JSON object matching this schema:\n"
                                                           f"{json.dumps(schema.model_json_schema())}"}, user]}
        try:   # structured output: Ollama constrains the reply to the JSON schema
            return self._post("/api/chat", dict(body, format=schema.model_json_schema()))["message"]["content"]
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            return self._post("/api/chat", dict(body, format="json"))["message"]["content"]   # older Ollama: JSON mode only

    def _run(self, system: str, text: str, schema, images=None):
        t0, errors = time.time(), []
        for attempt in range(self.retries + 1):
            try:
                x = schema.model_validate(parse_json(self._chat(system, text, schema, images)))
                dt = round(time.time() - t0, 2)
                return x, {"model": f"{self.model} (local)", "engine": "local", "latency_s": dt, "call_s": dt,
                           "attempts": attempt + 1, "errors": errors}
            except Exception as e:  # noqa: BLE001
                errors.append(f"{self.model}: {type(e).__name__}: {str(e)[:160]}")
        raise RuntimeError("local Gemma failed: " + " | ".join(errors))

    # ---- same interface as GeminiTriage ----
    def extract(self, transcript: str | None = None, image=None, audio=None):
        if audio is not None:
            raise RuntimeError("voice clips need Gemini: local Gemma reads text and photos only")
        return self._run(SYSTEM, f"CALL TRANSCRIPT:\n{transcript or ''}", Extract, [_b64(image)] if image is not None else None)

    def verify_frame(self, image, report: str | None = None):
        from .schema import CCTVCheck
        text = f"REPORT TO CHECK:\n{report}" if report else "No report yet: describe any emergency visible."
        return self._run(CCTV_SYSTEM, text, CCTVCheck, [_b64(image)])

    def write_advisory(self, facts: dict):
        from .prompt import ADVISORY_SYSTEM
        from .schema import Advisory
        return self._run(ADVISORY_SYSTEM, f"FACTS (JSON):\n{json.dumps(facts, ensure_ascii=False)}", Advisory)
