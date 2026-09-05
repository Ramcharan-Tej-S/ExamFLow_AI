# config.py — ExamFlow AI Configuration
import os

# ─── Paths ────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load secrets from .env (gitignored) before anything reads os.environ.
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BASE_DIR, ".env"))
except ImportError:  # dotenv is optional — real env vars still work
    pass

DB_PATH = os.path.join(BASE_DIR, "examflow.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "db", "schema.sql")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

# Ensure uploads dir exists
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ─── LLM (OpenRouter) ────────────────────────────────────────────────
# OpenRouter exposes an OpenAI-compatible endpoint, so any OpenAI client
# works against it by pointing base_url at their gateway.
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# Default is deliberately a cheap, fast, JSON-reliable model. Swap it with
# EXAMFLOW_MODEL — e.g. meta-llama/llama-3.3-70b-instruct is ~half the price,
# google/gemini-2.5-flash is stronger but dearer on output tokens.
LLM_MODEL = os.environ.get("EXAMFLOW_MODEL", "openai/gpt-4o-mini")

# Optional attribution headers OpenRouter shows on your activity dashboard.
OPENROUTER_APP_NAME = os.environ.get("OPENROUTER_APP_NAME", "ExamFlow AI")
OPENROUTER_SITE_URL = os.environ.get("OPENROUTER_SITE_URL", "http://localhost:8000")

# ─── Design Tokens (8-bit Arcade, Light) ───────────────────
COLORS = {
    "paper":    "#FDF6E3",   # Page ground
    "panel":    "#FFFFFF",   # Card surface
    "ink":      "#1A1A2E",   # Outlines + primary text
    "ink_soft": "#5A5A72",   # Muted text
    "red":      "#E63946",   # Hard / danger / 1-UP
    "blue":     "#2A6FDB",   # Primary action
    "yellow":   "#FFC94A",   # Coins / warning / medium
    "green":    "#3FA34D",   # Success / easy
    "purple":   "#7B4FBF",   # Highlight
    "orange":   "#F4801F",   # Secondary highlight
    "teal":     "#2AB7B0",   # Info
}

# ─── Difficulty Levels ───────────────────────────────────────────────
DIFFICULTY_LEVELS = ["easy", "medium", "hard"]

DIFFICULTY_LABELS = {
    "easy":   "🟢 Easy",
    "medium": "🟡 Medium",
    "hard":   "🔴 Hard",
}

DIFFICULTY_COLORS = {
    "easy":   COLORS["green"],
    "medium": COLORS["yellow"],
    "hard":   COLORS["red"],
}

# ─── Focus Time Slots ───────────────────────────────────────────────
FOCUS_SLOTS = {
    "early_morning": "🌅 Early Morning (5-8 AM)",
    "morning":       "☀️ Morning (8-11 AM)",
    "afternoon":     "🌤️ Afternoon (12-3 PM)",
    "evening":       "🌆 Evening (4-7 PM)",
    "night":         "🌙 Night (8-11 PM)",
}

# ─── LLM Factory ─────────────────────────────────────────────────────
def get_llm(temperature: float = 0.2, max_tokens: int = 2048, json_mode: bool = False):
    """Return a chat model bound to OpenRouter.

    Set json_mode=True to force a JSON object response — every agent that
    parses the reply with json.loads() relies on this.
    """
    from langchain_openai import ChatOpenAI

    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Put it in the project's .env file "
            "(OPENROUTER_API_KEY=sk-or-v1-...) or export it, then restart the server."
        )

    kwargs = dict(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        model=LLM_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=120,
        max_retries=2,
        default_headers={
            "HTTP-Referer": OPENROUTER_SITE_URL,
            "X-Title": OPENROUTER_APP_NAME,
        },
    )
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}

    return ChatOpenAI(**kwargs)
