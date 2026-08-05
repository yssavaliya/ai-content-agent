from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..agents.creator import CreatorAgent
from ..agents.planner import PlannerAgent
from ..agents.research import ResearchAgent
from ..agents.reviewer import ReviewerAgent
from ..database.connection import DatabaseConnection
from ..publish.providers.dry_run import DryRunPublisher
from ..providers.image import ImageProviderRegistry
from ..providers.image.base import ImageRequest
from ..settings import current_settings
from ..prompts.manager import PromptManager


class ContentPipeline:
    def __init__(self) -> None:
        self.settings = current_settings()
        self.prompt_manager = PromptManager(prompt_dir=Path("src/ai_content_agent/prompts"))
        self.research_agent = ResearchAgent()
        self.planner_agent = PlannerAgent()
        self.creator_agent = CreatorAgent()
        self.reviewer_agent = ReviewerAgent()
        self.image_provider = ImageProviderRegistry.get_provider(self.settings.image_provider)()
        self.publisher = DryRunPublisher()
        self.database = DatabaseConnection()

    def run(self) -> dict[str, Any]:
        try:
            research_results = self._run_research()
            planner_results = self._run_planner(research_results)
            planner_id = self._persist_planner_idea(planner_results, research_results["primary_research_id"])
            creator_results = self._run_creator(planner_results)
            creator_output_id = self._persist_creator_output(planner_id, creator_results)
            reviewer_results = self._run_reviewer(creator_results)
            image_result = self._run_image(creator_results, creator_output_id)

            package = {
                "research": research_results,
                "planning": planner_results,
                "creation": creator_results,
                "review": reviewer_results,
                "image": image_result,
                "publish": None,
            }

            package_path = self._save_package(package)
            publish_result = self._run_publish(creator_output_id, package_path)
            package["publish"] = publish_result
            self._save_package(package, package_path)
            return package
        finally:
            self.database.close()

    def _run_research(self) -> dict[str, Any]:
        research_output = self.research_agent.execute(
            {
                "identity": "brain/identity.md",
                "strategy": "brain/strategy.md",
                "prompt": "research.md",
            }
        )
        return research_output

    def _run_planner(self, research_output: dict[str, Any]) -> dict[str, Any]:
        return self.planner_agent.execute({"research_output": research_output})

    def _run_creator(self, planner_output: dict[str, Any]) -> dict[str, Any]:
        return self.creator_agent.execute(
            {
                "selected_idea": planner_output["selected_idea"],
                "identity": "brain/identity.md",
                "constitution": "brain/constitution.md",
                "strategy": "brain/strategy.md",
            }
        )

    def _run_reviewer(self, creator_output: dict[str, Any]) -> dict[str, Any]:
        return self.reviewer_agent.execute({"creator_output": creator_output})

    def _run_image(self, creator_output: dict[str, Any], creator_output_id: int) -> dict[str, Any]:
        request = ImageRequest(
            prompt=creator_output["image_prompt"],
            brand_style="clean",
            aspect_ratio="1:1",
        )
        image_result = self.image_provider.generate(request)
        self._persist_image_asset(creator_output_id, image_result)
        return image_result.__dict__

    def _run_publish(self, creator_output_id: int, package_path: Path) -> dict[str, Any]:
        result = self.publisher.publish(str(package_path))
        self._persist_publish_package(creator_output_id, result, package_path)
        return result.__dict__

    def _persist_planner_idea(self, planner_output: dict[str, Any], research_id: int | None) -> int:
        selected_idea = planner_output["selected_idea"]
        if isinstance(selected_idea, dict):
            idea_text = selected_idea.get("idea", str(selected_idea))
        else:
            idea_text = str(selected_idea)

        cursor = self.database.execute(
            "INSERT INTO planner_ideas(research_id, idea_text, educational_score, originality_score, engagement_score, relevance_score, total_score, selected, reasoning, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                research_id or 0,
                idea_text,
                0.8,
                0.7,
                0.9,
                0.8,
                3.2,
                1,
                "Selected by planner as the strongest content idea.",
                datetime.utcnow().isoformat() + "Z",
            ),
        )
        return cursor.lastrowid

    def _persist_creator_output(self, planner_id: int, creator_output: dict[str, Any]) -> int:
        cursor = self.database.execute(
            "INSERT INTO creator_outputs(planner_id, carousel_outline, caption, cta, hashtags, image_prompt, alt_text, markdown_path, json_path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                planner_id,
                json.dumps(creator_output["carousel_outline"]),
                creator_output["caption"],
                creator_output["cta"],
                json.dumps(creator_output["hashtags"]),
                creator_output["image_prompt"],
                "Generated image alt text.",
                "",
                "",
                datetime.utcnow().isoformat() + "Z",
            ),
        )
        return cursor.lastrowid

    def _persist_image_asset(self, creator_output_id: int, image_result: Any) -> int:
        cursor = self.database.execute(
            "INSERT INTO image_assets(creator_output_id, provider, prompt, file_path, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                creator_output_id,
                image_result.provider,
                image_result.prompt,
                image_result.file_path,
                json.dumps(image_result.metadata),
                datetime.utcnow().isoformat() + "Z",
            ),
        )
        return cursor.lastrowid

    def _persist_publish_package(self, creator_output_id: int, publish_result: Any, package_path: Path) -> int:
        cursor = self.database.execute(
            "INSERT INTO publish_packages(creator_output_id, status, published_id, package_path, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                creator_output_id,
                publish_result.status,
                publish_result.published_id,
                str(package_path),
                json.dumps(publish_result.metadata),
                datetime.utcnow().isoformat() + "Z",
            ),
        )
        return cursor.lastrowid

    def _save_package(self, package: dict[str, Any], path: Path | None = None) -> Path:
        output_dir = Path("posts")
        output_dir.mkdir(parents=True, exist_ok=True)
        if path is None:
            path = output_dir / f"publish_package_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.json"
        path.write_text(json.dumps(package, indent=2), encoding="utf-8")
        return path
