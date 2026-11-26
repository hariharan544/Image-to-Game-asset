"""AI supervisor backed by a local open model on the RTX 4080.

Talks to any OpenAI-compatible server (Ollama, LM Studio, llama.cpp server, vLLM):
  FORGE_LLM_URL     default http://localhost:11434/v1   (Ollama)
  FORGE_LLM_MODEL   default forge-supervisor            (your fine-tuned model; or e.g. qwen3:8b)
  FORGE_VLM_MODEL   vision model for visual critique, e.g. qwen2.5vl:7b (optional)
  FORGE_LLM_API_KEY only if your server needs one

Every answer is validated against the action space; anything invalid or any
connection error falls back to the rule supervisor, so a run never blocks on the AI.
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Optional

import httpx

from .base import Decision, Observation, Supervisor, actions_for, apply_action
from .prompt import CRITIQUE_SYSTEM, SYSTEM, user_message
from .rules import RuleSupervisor


def _extract_json(text: str) -> Optional[dict]:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)   # reasoning models
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _image_part(path: str) -> dict:
    data = base64.b64encode(Path(path).read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}}


class LLMSupervisor(Supervisor):
    name = "llm"

    def __init__(self, url: Optional[str] = None, model: Optional[str] = None,
                 vlm_model: Optional[str] = None, timeout: float = 120.0):
        self.url = (url or os.environ.get("FORGE_LLM_URL", "http://localhost:11434/v1")).rstrip("/")
        self.model = model or os.environ.get("FORGE_LLM_MODEL", "forge-supervisor")
        self.vlm_model = vlm_model or os.environ.get("FORGE_VLM_MODEL")
        self.key = os.environ.get("FORGE_LLM_API_KEY", "none")
        self.timeout = timeout
        self.fallback = RuleSupervisor()

    def _chat(self, model: str, messages: list[dict], max_tokens: int = 400) -> str:
        r = httpx.post(
            f"{self.url}/chat/completions",
            headers={"Authorization": f"Bearer {self.key}"},
            json={"model": model, "messages": messages, "temperature": 0.1, "max_tokens": max_tokens},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def available(self) -> bool:
        try:
            return httpx.get(f"{self.url}/models", timeout=5,
                             headers={"Authorization": f"Bearer {self.key}"}).status_code == 200
        except httpx.HTTPError:
            return False

    def decide(self, obs: Observation) -> Decision:
        allowed = actions_for(obs.stage)
        try:
            text = self._chat(self.model, [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_message(obs)},
            ])
            ans = _extract_json(text) or {}
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            d = self.fallback.decide(obs)
            d.reason = f"[AI offline: {type(exc).__name__}] {d.reason}"
            return d
        action = ans.get("action")
        if action not in allowed:
            d = self.fallback.decide(obs)
            d.reason = f"[AI answered invalid action {action!r}] {d.reason}"
            return d
        # never accept over a blocking error; that is the QA gate's job, not the AI's
        if action == "accept" and any(i.get("severity", "error") == "error" for i in obs.issues):
            d = self.fallback.decide(obs)
            d.reason = f"[AI tried to accept with blocking issues] {d.reason}"
            return d
        new_params = apply_action(action, obs.params) if action not in ("accept", "escalate") else None
        return Decision(action, str(ans.get("reason", ""))[:500], f"llm:{self.model}", new_params)

    def critique(self, images: list[str], reference_images: list[str], notes: str) -> Optional[dict]:
        if not self.vlm_model:
            return None
        content: list[dict] = [{"type": "text", "text": f"Creative notes: {notes or '-'}\nCONCEPT IMAGE(S):"}]
        content += [_image_part(p) for p in reference_images if Path(p).exists()]
        content.append({"type": "text", "text": "GAME-READY MODEL RENDERS:"})
        content += [_image_part(p) for p in images if Path(p).exists()]
        try:
            text = self._chat(self.vlm_model, [
                {"role": "system", "content": CRITIQUE_SYSTEM},
                {"role": "user", "content": content},
            ], max_tokens=800)
        except (httpx.HTTPError, KeyError, ValueError):
            return None
        ans = _extract_json(text)
        if not ans or ans.get("verdict") not in ("approve", "needs_work"):
            return None
        return {"verdict": ans["verdict"], "observations": [str(o) for o in ans.get("observations", [])][:20],
                "model": self.vlm_model}
