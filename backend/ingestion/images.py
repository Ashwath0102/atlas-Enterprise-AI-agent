"""
backend/ingestion/images.py
────────────────────────────
Dashboard screenshot and wiki image ingestion pipeline.

Pipeline per image:
  1. Load image with PIL.
  2. Send to LLM_BULK_MODEL (Gemini vision) with a structured OCR + description prompt.
  3. Cross-reference against data/images/ground_truth.md for chart images.
  4. Embed the description + upsert into Qdrant with modality="image".

Volume: 6 images — negligible quota impact.
Resume-safe: keyed by SHA-256(image_bytes + model + "image_describe").
"""

from __future__ import annotations

import base64
import io
import logging
import time
from pathlib import Path
from typing import List, Optional

import httpx
from PIL import Image
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from backend.config import settings
from backend.ingestion.base import (
    Chunk,
    embed_texts,
    ensure_collection,
    get_embed_dim,
    get_qdrant_client,
    upsert_chunks,
)
from backend.rate_limiter import cache_manager

logger = logging.getLogger("atlas.ingestion.images")
console = Console(highlight=False)

_IMAGE_DIR = Path("data/images")
_GROUND_TRUTH_PATH = Path("data/images/ground_truth.md")
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_RESIZE_MAX = (1024, 768)  # max dimensions before sending to API


# ─────────────────────────────────────────────────────────────────────────────
# Ground-truth loader
# ─────────────────────────────────────────────────────────────────────────────

def _load_ground_truth() -> dict:
    """Return a dict mapping filename → ground truth text block."""
    if not _GROUND_TRUTH_PATH.exists():
        return {}
    content = _GROUND_TRUTH_PATH.read_text(encoding="utf-8")
    sections: dict = {}
    current_file: Optional[str] = None
    lines: List[str] = []
    for line in content.splitlines():
        # Lines like: "## dash_status.png — ..."
        if line.startswith("## ") and ".png" in line:
            if current_file and lines:
                sections[current_file] = "\n".join(lines).strip()
            parts = line[3:].strip().split(" — ")
            current_file = parts[0].strip()
            lines = [line]
        elif current_file:
            lines.append(line)
    if current_file and lines:
        sections[current_file] = "\n".join(lines).strip()
    return sections


# ─────────────────────────────────────────────────────────────────────────────
# Gemini vision
# ─────────────────────────────────────────────────────────────────────────────

_OCR_PROMPT = """You are analyzing a dashboard screenshot or wiki image from a Jira/Confluence environment.

Provide a structured description with these sections:
1. **Image type**: (dashboard chart / wiki page / screenshot / other)
2. **Title**: The main title visible on the image (if any)
3. **Content summary**: 2-3 sentences describing what is shown
4. **Visible text**: All significant text visible in the image (titles, labels, legend items, axis labels, numbers)
5. **Data values**: If this is a chart, list every data point, count, or percentage visible
6. **UI elements**: Buttons, menus, fields, or navigation elements visible

Be exhaustive with numbers and text — this will be used for search and accuracy evaluation."""


def _model_id(m: str) -> str:
    return m[len("models/"):] if m.startswith("models/") else m


def _describe_image(image_bytes: bytes, filename: str, ground_truth: str = "") -> str:
    """Describe an image using Gemini vision. Includes ground truth hint if available."""
    import random
    model = settings.LLM_BULK_MODEL
    mid = _model_id(model)
    url = f"{_GEMINI_BASE}/models/{mid}:generateContent"

    prompt = _OCR_PROMPT
    if ground_truth:
        prompt += f"\n\n**Known ground truth for reference** (use to verify your reading):\n{ground_truth}"

    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    # Detect mime type
    mime = "image/jpeg" if filename.lower().endswith((".jpg", ".jpeg")) else "image/png"

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": mime, "data": image_b64}},
                    {"text": prompt},
                ],
            }
        ]
    }

    for attempt in range(4):
        try:
            resp = httpx.post(
                url,
                params={"key": settings.GEMINI_API_KEY},
                json=payload,
                timeout=45,
            )
            if resp.status_code == 429:
                wait = min(2 ** attempt + random.uniform(0, 1), 60)
                logger.warning("Image vision 429 — sleeping %.1fs", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts if "text" in p).strip()
        except Exception as exc:
            if attempt < 3:
                time.sleep(2 ** attempt)
            else:
                logger.error("Image vision failed for %s: %s", filename, exc)
                return f"Image: {filename} (description failed)"

    return f"Image: {filename}"


# ─────────────────────────────────────────────────────────────────────────────
# Cache helpers
# ─────────────────────────────────────────────────────────────────────────────

def _img_cache_key(path: Path) -> str:
    return cache_manager.get_cache_key(str(path), settings.LLM_BULK_MODEL, "image_describe")


def _is_cached(path: Path) -> bool:
    return cache_manager.exists(_img_cache_key(path))


def _cache_result(path: Path, description: str) -> None:
    cache_manager.set(_img_cache_key(path), {"description": description, "file": str(path)})


def _load_cached(path: Path) -> Optional[str]:
    data = cache_manager.get(_img_cache_key(path))
    return data.get("description") if data else None


# ─────────────────────────────────────────────────────────────────────────────
# Image preprocessing
# ─────────────────────────────────────────────────────────────────────────────

def _prepare_image(path: Path) -> bytes:
    """Load, resize if needed, and return JPEG/PNG bytes."""
    img = Image.open(path).convert("RGB")
    # Resize if too large
    if img.width > _RESIZE_MAX[0] or img.height > _RESIZE_MAX[1]:
        img.thumbnail(_RESIZE_MAX, Image.LANCZOS)

    buf = io.BytesIO()
    # Keep PNG for screenshots to preserve text clarity
    fmt = "PNG" if path.suffix.lower() == ".png" else "JPEG"
    img.save(buf, format=fmt, quality=90 if fmt == "JPEG" else None)
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────────────────────
# Main ingestion function
# ─────────────────────────────────────────────────────────────────────────────

def ingest_images(image_dir: Path = _IMAGE_DIR, force: bool = False) -> int:
    """Ingest all PNG/JPG images from image_dir into Qdrant.

    Returns the number of image chunks upserted.
    """
    # Collect image files (skip ground_truth.md and non-image files)
    image_files = sorted(
        p for p in image_dir.iterdir()
        if p.suffix.lower() in (".png", ".jpg", ".jpeg") and p.is_file()
    )
    if not image_files:
        logger.warning("No image files found in %s", image_dir)
        return 0

    ground_truth = _load_ground_truth()
    logger.info("Images: found %d files, %d ground-truth entries", len(image_files), len(ground_truth))

    qdrant_client = get_qdrant_client()
    dim = get_embed_dim()
    ensure_collection(qdrant_client, dim)

    chunks: List[Chunk] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Images[/bold blue] {task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("describing", total=len(image_files))

        for img_path in image_files:
            progress.update(task, description=img_path.name)

            # ── Check cache ───────────────────────────────────────────────────
            description: Optional[str] = None
            if not force and _is_cached(img_path):
                description = _load_cached(img_path)
                logger.info("Images: %s loaded from cache", img_path.name)

            if description is None:
                gt_text = ground_truth.get(img_path.name, "")
                image_bytes = _prepare_image(img_path)
                description = _describe_image(image_bytes, img_path.name, gt_text)
                _cache_result(img_path, description)
                time.sleep(0.5)  # small pause between vision calls

            # ── Build chunk ───────────────────────────────────────────────────
            source_id = f"image/{img_path.stem}"
            # Augment with ground truth if available
            full_text = description
            if img_path.name in ground_truth:
                full_text = (
                    f"{description}\n\n"
                    f"GROUND TRUTH DATA:\n{ground_truth[img_path.name]}"
                )

            chunks.append(Chunk(
                source_id=source_id,
                modality="image",
                file=str(img_path),
                text=full_text,
                metadata={
                    "filename": img_path.name,
                    "has_ground_truth": img_path.name in ground_truth,
                },
            ))
            progress.advance(task)

    # ── Embed + upsert all at once (only 6 images) ────────────────────────────
    if not chunks:
        return 0

    vectors = embed_texts([c.text for c in chunks])
    upsert_chunks(qdrant_client, chunks, vectors)
    logger.info("Images: upserted %d chunks", len(chunks))
    return len(chunks)

