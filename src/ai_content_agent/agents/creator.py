from __future__ import annotations

from .base import BaseAgent


class CreatorAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "CreatorAgent"

    @property
    def description(self) -> str:
        return "Creates a post draft based on the selected content idea."

    @property
    def input_schema(self) -> dict[str, str]:
        return {
            "selected_idea": "Selected idea from PlannerAgent",
            "identity": "Path to identity documentation",
            "constitution": "Path to constitution documentation",
            "strategy": "Path to strategy documentation",
        }

    @property
    def output_schema(self) -> dict[str, str]:
        return {
            "carousel_outline": "Outline of post carousel slides",
            "caption": "Suggested post caption",
            "cta": "Call to action text",
            "hashtags": "List of hashtags",
            "image_prompt": "Prompt for the image provider",
        }

    def execute(self, inputs: dict[str, object]) -> dict[str, object]:
        return {
            "carousel_outline": [
                "Slide 1: Trend introduction",
                "Slide 2: Why it matters",
                "Slide 3: Actionable tip",
            ],
            "caption": "A placeholder caption for the selected idea.",
            "cta": "Tell us what you think in the comments.",
            "hashtags": ["#content", "#strategy", "#socialmedia"],
            "image_prompt": "A clean social media carousel image with bold typography.",
        }
