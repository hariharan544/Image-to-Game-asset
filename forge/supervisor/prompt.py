"""The exact prompt format the AI supervisor sees.

Used both at run time (llm.py) and when building training data
(training/build_dataset.py) so the fine-tuned model is trained on precisely
what it will be shown.
"""

from __future__ import annotations

import json

from .base import Observation, actions_for

SYSTEM = """You are the technical-art supervisor of an automated game-asset pipeline \
(AI-generated 3D model -> Blender cleanup, retopology, UVs, baking, skinning -> Unity/Unreal).
After each stage you receive measured metrics and QA issues. Choose ONE action from the \
allowed list that is most likely to fix the blocking issues without hurting quality, \
'accept' when only warnings remain and they are acceptable for the asset's tier, or \
'escalate' when a human must decide. Do not repeat an action that already failed for the \
same issue unless the history shows it helped.
Answer with JSON only: {"action": "<name>", "reason": "<one sentence>"}"""

CRITIQUE_SYSTEM = """You are a senior technical artist reviewing a finished game asset. \
Compare the renders of the game-ready model with the concept image(s). Report concrete, \
visible problems only (missing parts, texture seams/smearing, wrong proportions, shading \
artifacts, parts that should be separate). Answer with JSON only: \
{"verdict": "approve" | "needs_work", "observations": ["...", "..."]}"""


def _compact(result: dict, limit: int = 3000) -> str:
    text = json.dumps(result, separators=(",", ":"), default=str)
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


def user_message(obs: Observation) -> str:
    allowed = actions_for(obs.stage)
    lines = [
        f"ASSET: {obs.asset}",
        f"STAGE: {obs.stage} (attempt {obs.attempt})",
        f"BUDGET: {json.dumps(obs.budget)}",
        f"CREATIVE NOTES: {obs.notes.strip() or '-'}",
        f"CURRENT PARAMS: {json.dumps(obs.params, default=str)}",
        f"METRICS: {_compact(obs.result)}",
        "QA ISSUES:",
    ]
    lines += [f"- [{i.get('severity')}] {i['code']} part={i.get('part')} value={i.get('value')} "
              f"limit={i.get('limit')}: {i.get('message')}" for i in obs.issues] or ["- none"]
    lines.append("HISTORY:")
    lines += [f"- attempt {h.get('attempt')}: action={h.get('action')} -> issues={h.get('issue_codes')}"
              for h in obs.history] or ["- none"]
    lines.append("ALLOWED ACTIONS:")
    lines += [f"- {name}: {desc}" for name, desc in allowed.items()]
    return "\n".join(lines)


def assistant_message(action: str, reason: str) -> str:
    return json.dumps({"action": action, "reason": reason})
