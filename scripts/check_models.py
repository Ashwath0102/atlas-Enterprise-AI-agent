"""
scripts/check_models.py
───────────────────────
Validates every configured model name against the live provider APIs using
direct REST calls (compatible with Python 3.8+).

Usage:
    python scripts/check_models.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# ── Load .env from project root before importing config ──────────────────────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from backend.config import settings  # noqa: E402

import httpx
from groq import Groq
from rich.console import Console
from rich.table import Table

console = Console()

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_gemini_models() -> list[str]:
    """Return list of Gemini model names via REST (works on Python 3.8+)."""
    url = f"{_GEMINI_BASE}/models"
    resp = httpx.get(url, params={"key": settings.GEMINI_API_KEY}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return [m["name"] for m in data.get("models", [])]


def _fetch_groq_models() -> list[str]:
    """Return list of Groq model IDs."""
    client = Groq(api_key=settings.GROQ_API_KEY)
    result = client.models.list()
    return [m.id for m in result.data]


def _model_in_list(model: str, model_list: list[str]) -> bool:
    """Check if *model* appears in *model_list* (with or without 'models/' prefix)."""
    return (
        model in model_list
        or f"models/{model}" in model_list
        or model.lstrip("models/") in model_list
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    console.rule("[bold blue]Atlas — Model Availability Check")

    # ── Fetch model lists ────────────────────────────────────────────────────
    console.print("\n[cyan]Fetching Gemini model list…")
    try:
        gemini_models = _fetch_gemini_models()
        console.print(f"  Found [green]{len(gemini_models)}[/green] Gemini models")
        for name in sorted(gemini_models):
            console.print(f"    • {name}", style="dim")
    except Exception as exc:
        console.print(f"  [red]ERROR fetching Gemini models: {exc}")
        gemini_models = []

    console.print("\n[cyan]Fetching Groq model list…")
    try:
        groq_models = _fetch_groq_models()
        console.print(f"  Found [green]{len(groq_models)}[/green] Groq models")
        for name in sorted(groq_models):
            console.print(f"    • {name}", style="dim")
    except Exception as exc:
        console.print(f"  [red]ERROR fetching Groq models: {exc}")
        groq_models = []

    # ── Define checks ────────────────────────────────────────────────────────
    checks = [
        ("LLM_PRIMARY_MODEL",   settings.LLM_PRIMARY_MODEL,   "gemini",  gemini_models),
        ("LLM_BULK_MODEL",      settings.LLM_BULK_MODEL,       "gemini",  gemini_models),
        ("LLM_FALLBACK_MODEL",  settings.LLM_FALLBACK_MODEL,   "groq",    groq_models),
        ("EMBEDDING_MODEL",     settings.EMBEDDING_MODEL,      "gemini",  gemini_models),
        ("TTS_MODEL",           settings.TTS_MODEL,            "gemini",  gemini_models),
        ("STT_MODEL",           settings.STT_MODEL,            "groq",    groq_models),
    ]

    # ── Build result table ───────────────────────────────────────────────────
    table = Table(title="Model Validation Results", show_lines=True)
    table.add_column("Config Key",     style="bold")
    table.add_column("Model Name",     style="cyan")
    table.add_column("Provider",       style="yellow")
    table.add_column("Status",         justify="center")

    any_fail = False
    for key, model, provider, model_list in checks:
        found = _model_in_list(model, model_list) if model_list else False
        if found:
            status = "[bold green]PASS"
        else:
            status = "[bold red]FAIL"
            any_fail = True
        table.add_row(key, model, provider, status)

    console.print()
    console.print(table)
    console.print()

    if any_fail:
        console.print("[bold red]One or more configured models were NOT found in the provider's model list.")
        console.print("Check your .env and update the model names accordingly.")
        sys.exit(1)
    else:
        console.print("[bold green]All configured models validated successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
