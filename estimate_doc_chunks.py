"""
Estimates how many embedding API calls the GitLab handbook subset will need,
with and without batching, and checks it against the real Gemini Embedding
free-tier daily limit (1,000 RPD). Also does a quick sanity count on 
dashboard images.



Usage:
    python estimate_doc_chunks.py --project-root C:\IBM_BOB\Entreprise
"""
import argparse
from pathlib import Path

EMBEDDING_RPD_LIMIT = 1000       # Gemini Embedding free tier, requests/day
EMBEDDING_RPM_LIMIT = 100        # requests/minute
CHUNK_SIZE_TOKENS = 500          # typical chunk size for RAG
BATCH_SIZE = 20                  # chunks per embedding API call, if batched
CHARS_PER_TOKEN = 4              # rough rule-of-thumb estimate, no tokenizer needed

HANDBOOK_SUBFOLDERS_TO_TRY = ["support", "customer-success", "customer-experience", "onboarding"]


def find_handbook_root(project_root: Path) -> Path:
    candidate = project_root / "data" / "docs" / "gitlab-handbook" / "content" / "handbook"
    if not candidate.exists():
        raise SystemExit(f"Handbook folder not found at {candidate}")
    return candidate


def count_tokens_in_file(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0
    return len(text) // CHARS_PER_TOKEN


def estimate_docs(project_root: Path):
    handbook_root = find_handbook_root(project_root)

    used_subfolders = []
    total_files = 0
    total_tokens = 0

    for name in HANDBOOK_SUBFOLDERS_TO_TRY:
        sub = handbook_root / name
        if not sub.exists():
            continue
        used_subfolders.append(name)
        md_files = list(sub.rglob("*.md"))
        total_files += len(md_files)
        for f in md_files:
            total_tokens += count_tokens_in_file(f)

    if not used_subfolders:
        print(f"WARNING: none of {HANDBOOK_SUBFOLDERS_TO_TRY} found under {handbook_root}")
        print("Check the actual folder names with:")
        print(f'  dir "{handbook_root}" /b')
        return

    est_chunks = max(1, -(-total_tokens // CHUNK_SIZE_TOKENS))  # ceil division
    calls_unbatched = est_chunks
    calls_batched = max(1, -(-est_chunks // BATCH_SIZE))

    print("=== GitLab handbook chunk estimate ===")
    print(f"Subfolders found and used: {used_subfolders}")
    print(f"Markdown files: {total_files}")
    print(f"Estimated tokens: {total_tokens:,}")
    print(f"Estimated chunks (at {CHUNK_SIZE_TOKENS} tokens/chunk): {est_chunks:,}\n")

    print(f"Gemini Embedding free tier: {EMBEDDING_RPD_LIMIT} requests/day, {EMBEDDING_RPM_LIMIT}/minute\n")

    print(f"If UNBATCHED (1 chunk per API call): {calls_unbatched:,} calls needed")
    if calls_unbatched > EMBEDDING_RPD_LIMIT:
        over = calls_unbatched - EMBEDDING_RPD_LIMIT
        print(f"  -> EXCEEDS daily limit by {over:,} calls. Batching is required, not optional.")
    else:
        print(f"  -> fits within daily limit ({EMBEDDING_RPD_LIMIT - calls_unbatched:,} calls to spare)")

    print(f"\nIf BATCHED ({BATCH_SIZE} chunks per API call): {calls_batched:,} calls needed")
    if calls_batched > EMBEDDING_RPD_LIMIT:
        print(f"  -> still exceeds daily limit — increase BATCH_SIZE or reduce ingested subfolders")
    else:
        print(f"  -> fits comfortably ({EMBEDDING_RPD_LIMIT - calls_batched:,} calls to spare)")
        minutes_needed = calls_batched / EMBEDDING_RPM_LIMIT
        print(f"  -> at {EMBEDDING_RPM_LIMIT} RPM, takes about {minutes_needed:.1f} minutes of steady calling")


def estimate_images(project_root: Path):
    img_dir = project_root / "data" / "images"
    if not img_dir.exists():
        print("\n(no data/images folder found — skipping image count)")
        return
    images = [p for p in img_dir.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
    print(f"\n=== Dashboard/wiki images ===")
    print(f"Found {len(images)} image(s) — well within any daily vision quota, no scheduling needed.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", required=True, help=r"e.g. C:\IBM_BOB\Entreprise")
    args = ap.parse_args()

    root = Path(args.project_root)
    if not root.exists():
        raise SystemExit(f"Project root not found: {root}")

    estimate_docs(root)
    estimate_images(root)


if __name__ == "__main__":
    main()
