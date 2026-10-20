"""Import smoke test for Phase 4 agent modules."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

print("Importing agent modules...")
from backend.agent.state import empty_state
print("  state OK")
from backend.agent.llm import llm_call
print("  llm OK")
from backend.agent.tracer import Tracer
print("  tracer OK")
from backend.agent.nodes.planner import planner_node
print("  planner OK")
from backend.agent.nodes.retrieval_node import retrieval_node
print("  retrieval_node OK")
from backend.agent.nodes.vision_node import vision_node
print("  vision_node OK")
from backend.agent.nodes.action_node import action_node
print("  action_node OK")
from backend.agent.nodes.synthesizer import synthesizer_node
print("  synthesizer OK")
from backend.agent.graph import AtlasGraph
print("  graph OK")

# Verify state shape
s = empty_state("test question")
assert s["question"] == "test question"
assert s["retrieved_chunks"] == []
assert s["answer"] is None
print("\nAll imports OK — state shape correct")
