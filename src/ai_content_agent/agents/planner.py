from __future__ import annotations

from .base import BaseAgent


class PlannerAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "PlannerAgent"

    @property
    def description(self) -> str:
        return "Generates multiple content ideas and selects the best one."

    @property
    def input_schema(self) -> dict[str, str]:
        return {
            "research_output": "Structured output from ResearchAgent",
        }

    @property
    def output_schema(self) -> dict[str, str]:
        return {
            "ideas": "List of candidate ideas with scores",
            "selected_idea": "Best idea selected for creation",
        }

    def execute(self, inputs: dict[str, object]) -> dict[str, object]:
        return {
            "ideas": [
                {"idea": "Create a post about trend-a", "score": 0.8},
                {"idea": "Share insights on trend-b", "score": 0.6},
            ],
            "selected_idea": {"idea": "Create a post about trend-a", "score": 0.8},
        }
