"""Print the Gemini/Gemma models your key can use, so you can set GEMINI_MODEL / FALLBACK_MODELS in .env."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import os
from google import genai
from csafe.triage.client import load_env
load_env()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
for m in client.models.list():
    acts = getattr(m, "supported_actions", None) or []
    if not acts or "generateContent" in acts:
        print(m.name.replace("models/", ""))
