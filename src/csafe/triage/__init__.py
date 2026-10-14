"""112 call triage: Gemini extracts facts from a call (text, audio or photo); fixed rules decide
priority and units. The model never decides on its own how urgent a call is."""
from .schema import Extract, Decision  # noqa: F401
from .rules import decide  # noqa: F401
