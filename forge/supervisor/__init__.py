from .base import ACTIONS, Decision, Observation, Supervisor, actions_for, apply_action
from .llm import LLMSupervisor
from .rules import RuleSupervisor


def make_supervisor(backend: str) -> Supervisor:
    return LLMSupervisor() if backend == "llm" else RuleSupervisor()


__all__ = ["ACTIONS", "Decision", "Observation", "Supervisor", "actions_for", "apply_action",
           "LLMSupervisor", "RuleSupervisor", "make_supervisor"]
