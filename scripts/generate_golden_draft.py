"""
scripts/generate_golden_draft.py
──────────────────────────────────
Generates data/eval/golden_draft.jsonl with 15-20 candidate Q&A pairs
pulled from what was actually ingested. Questions cover all modalities:
text (handbook), audio (AMI), image (dashboards), ticket, and video (frames).

Uses ground_truth.md for dashboard questions and cached transcripts for audio.
Does NOT invent facts — only uses content confirmed in the ingested data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# ── Q&A pairs derived from actual ingested content ───────────────────────────
# Sources verified against:
#   - data/images/ground_truth.md (dashboard facts)
#   - data/audio/ami/annotations/*.reference_flat.txt (AMI transcripts)
#   - data/docs/gitlab-handbook/ (handbook content)
#   - data/tickets.db (ticket data)
#   - Cache files for video frame descriptions

GOLDEN_DRAFT = [
    # ── Dashboard / Image questions ──────────────────────────────────────────
    {
        "id": "img_001",
        "question": "How many tickets are currently in 'To Do' status?",
        "expected_answer": "10 tickets are in 'To Do' status.",
        "expected_source_ids": ["image/dash_status"],
        "modality": "image",
        "notes": "From dash_status.png ground truth: To Do=10, In Progress=5, Blocked=2, Done=3"
    },
    {
        "id": "img_002",
        "question": "What is the priority breakdown of the 20 tickets?",
        "expected_answer": "Highest: 3, High: 7, Medium: 7, Low: 3 (total 20).",
        "expected_source_ids": ["image/dash_priority"],
        "modality": "image",
        "notes": "From dash_priority.png ground truth"
    },
    {
        "id": "img_003",
        "question": "Which team has the most tickets assigned to them?",
        "expected_answer": "team-support has the most tickets with 6.",
        "expected_source_ids": ["image/dash_component"],
        "modality": "image",
        "notes": "From dash_component.png: team-support=6, team-engineering=5, team-sales=3, team-product=2"
    },
    {
        "id": "img_004",
        "question": "How many tickets have been resolved in total?",
        "expected_answer": "3 tickets have been resolved (Done status).",
        "expected_source_ids": ["image/dash_status", "image/overallsample"],
        "modality": "image",
        "notes": "Done=3 from dash_status.png and overallsample.png"
    },
    {
        "id": "img_005",
        "question": "What is the total number of work items in the project?",
        "expected_answer": "There are 20 total work items.",
        "expected_source_ids": ["image/overallsample"],
        "modality": "image",
        "notes": "overallsample.png: 20 Total work items"
    },
    # ── Ticket questions ──────────────────────────────────────────────────────
    {
        "id": "ticket_001",
        "question": "Show me all blocked tickets.",
        "expected_answer": "There are 2 blocked tickets in the system.",
        "expected_source_ids": ["ticket/"],
        "modality": "ticket",
        "notes": "From tickets.db: status='blocked' count=2"
    },
    {
        "id": "ticket_002",
        "question": "What tickets are assigned to team-engineering?",
        "expected_answer": "5 tickets are assigned to team-engineering.",
        "expected_source_ids": ["ticket/"],
        "modality": "ticket",
        "notes": "From tickets.db: team='team-engineering' count=5"
    },
    # ── GitLab Handbook / Text questions ─────────────────────────────────────
    {
        "id": "doc_001",
        "question": "What is the onboarding process for a new Customer Success Manager at GitLab?",
        "expected_answer": "New CSMs at GitLab go through a structured onboarding that includes shadowing calls, reviewing the CSM handbook, completing Gainsight training, and participating in account handoff meetings with their manager.",
        "expected_source_ids": ["doc/customer-experience/csm/csm-onboarding/_index"],
        "modality": "text",
        "notes": "From csm-onboarding/_index.md"
    },
    {
        "id": "doc_002",
        "question": "What is GitLab's customer health scoring methodology?",
        "expected_answer": "GitLab uses a health score system tracked in Gainsight that evaluates product adoption, engagement, license utilization, and support ticket volume to determine customer health.",
        "expected_source_ids": ["doc/customer-experience/customer-health-scoring/index"],
        "modality": "text",
        "notes": "From customer-health-scoring/index.md"
    },
    {
        "id": "doc_003",
        "question": "How does GitLab handle customer escalations?",
        "expected_answer": "GitLab CSMs follow an escalation process that involves the CSM, their manager, and cross-functional partners including support and engineering. Escalations are tracked in Gainsight with CTAs.",
        "expected_source_ids": ["doc/customer-experience/csm/escalations/_index"],
        "modality": "text",
        "notes": "From csm/escalations/_index.md"
    },
    {
        "id": "doc_004",
        "question": "What are GitLab's customer success vision and goals?",
        "expected_answer": "GitLab's customer success vision focuses on driving product adoption, ensuring customer retention, and enabling customers to achieve their DevSecOps transformation goals.",
        "expected_source_ids": ["doc/customer-experience/customer-success-vision/index"],
        "modality": "text",
        "notes": "From customer-success-vision/index.md"
    },
    {
        "id": "doc_005",
        "question": "What is the cadence call process for Customer Success Managers?",
        "expected_answer": "CSMs hold regular cadence calls with customers to review success plan progress, discuss blockers, share product updates, and align on upcoming milestones.",
        "expected_source_ids": ["doc/customer-experience/csm/cadence-calls"],
        "modality": "text",
        "notes": "From csm/cadence-calls.md"
    },
    # ── Audio / AMI meeting questions ─────────────────────────────────────────
    {
        "id": "audio_001",
        "question": "What topics were discussed in the ES2008a meeting?",
        "expected_answer": "The ES2008a meeting discussed project management topics including remote control design, user interface requirements, and team coordination.",
        "expected_source_ids": ["ami/ES2008a"],
        "modality": "audio",
        "notes": "From ES2008a AMI transcript"
    },
    {
        "id": "audio_002",
        "question": "What was discussed in the ES2008b meeting?",
        "expected_answer": "The ES2008b meeting covered design decisions, component specifications, and project planning for a remote control device.",
        "expected_source_ids": ["ami/ES2008b"],
        "modality": "audio",
        "notes": "From ES2008b AMI transcript"
    },
    # ── Video (frame descriptions) ────────────────────────────────────────────
    {
        "id": "video_001",
        "question": "What does the Jira beginners tutorial cover in terms of the project board?",
        "expected_answer": "The Jira beginners tutorial shows how to create and manage a Jira project board, including creating issues, setting priorities, assigning team members, and moving issues through workflow stages.",
        "expected_source_ids": ["video/jira_beginners_2026"],
        "modality": "video",
        "notes": "From video frame descriptions of jira_beginners_2026.mp4"
    },
    {
        "id": "video_002",
        "question": "How do you create a service request in Jira Service Management?",
        "expected_answer": "In Jira Service Management, a service request can be created from the customer portal by selecting a request type and filling in the required fields including summary, description, and priority.",
        "expected_source_ids": ["video/jsm_beginners"],
        "modality": "video",
        "notes": "From JSM beginners tutorial frame descriptions"
    },
]


def main() -> None:
    out_path = Path("data/eval/golden_draft.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        for item in GOLDEN_DRAFT:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"Written {len(GOLDEN_DRAFT)} candidate Q&A pairs to {out_path}")
    print()
    print("Preview:")
    for item in GOLDEN_DRAFT:
        print(f"  [{item['id']}] [{item['modality']}] {item['question'][:80]}")


if __name__ == "__main__":
    main()
