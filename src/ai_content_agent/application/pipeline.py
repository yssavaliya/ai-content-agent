from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from ..agents.creator import CreatorAgent
from ..agents.planner import PlannerAgent
from ..agents.research import ResearchAgent
from ..agents.reviewer import ReviewerAgent
from ..database.connection import DatabaseConnection
from ..notifications.channels import DryRunChannel
from ..notifications.notifier import Notifier
from ..prompts.manager import PromptManager
from ..providers.image import ImageProviderRegistry
from ..providers.image.base import BaseImageProvider, ImageRequest
from ..publish.hosting import GitHubRawImageHost, MediaHostingError, convert_to_jpeg
from ..publish.provider import PublishResult, Publisher
from ..publish.registry import PublishRegistry
from ..science.experiments import ExperimentRepository
from ..settings import Settings, current_settings
from ..timestamps import utc_now_iso

logger = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    pass


class ContentPipeline:
    def __init__(
        self,
        settings: Settings | None = None,
        database: DatabaseConnection | None = None,
        notifier: Notifier | None = None,
        image_provider: BaseImageProvider | None = None,
        publisher: Publisher | None = None,
    ) -> None:
        self.settings = settings or current_settings()
        self.prompt_manager = PromptManager(prompt_dir=Path("src/ai_content_agent/prompts"))
        self.database = database or DatabaseConnection()
        self._owns_database = database is None
        self.notifier = notifier or Notifier([DryRunChannel()])
        self.image_provider = image_provider or ImageProviderRegistry.get_provider(self.settings.image_provider)()
        self.publisher = publisher or PublishRegistry.build_publisher(self.settings)
        self.experiments = ExperimentRepository(self.database)
        self.research_agent: ResearchAgent | None = None
        self.planner_agent: PlannerAgent | None = None
        self.creator_agent: CreatorAgent | None = None
        self.reviewer_agent: ReviewerAgent | None = None

    def _ensure_agents(self) -> None:
        if self.research_agent is None:
            self.research_agent = ResearchAgent(
                prompt_manager=self.prompt_manager,
                database=self.database,
            )
        if self.planner_agent is None:
            self.planner_agent = PlannerAgent(
                prompt_manager=self.prompt_manager,
                database=self.database,
            )
        if self.creator_agent is None:
            self.creator_agent = CreatorAgent(
                prompt_manager=self.prompt_manager,
                database=self.database,
            )
        if self.reviewer_agent is None:
            self.reviewer_agent = ReviewerAgent(
                prompt_manager=self.prompt_manager,
                database=self.database,
            )

    def run(self, run_id: str | None = None) -> dict[str, Any]:
        run_id = run_id or uuid.uuid4().hex[:8]
        logger.info("Pipeline run %s starting", run_id)
        try:
            package = self._produce_content(run_id)
            self._save_package(package, package.get("package_path"))
            self.notifier.send_success(
                subject="AI Content Agent: daily post published",
                body=self._success_body(package, run_id),
                metadata={"run_id": run_id, "color": 3066993},
            )
            logger.info("Pipeline run %s completed", run_id)
            return package
        except Exception as exc:
            logger.exception("Pipeline run %s failed", run_id)
            self.notifier.send_failure(
                subject="AI Content Agent: daily run FAILED",
                body=self._failure_body(exc, run_id),
                metadata={"run_id": run_id, "color": 15158332},
            )
            raise
        finally:
            self.close()

    def _produce_content(self, run_id: str) -> dict[str, Any]:
        with self.database.transaction():
            research_results = self._run_research()
            research_id = research_results.get("research_id")
            if not isinstance(research_id, int) or research_id <= 0:
                raise PipelineError(
                    "ResearchAgent did not return a valid research_id; aborting to avoid orphan rows"
                )

            planner_results = self._run_planner(research_results)
            planner_id = self._persist_planner_idea(planner_results, research_id)

            creator_results = self._run_creator(planner_results)
            creator_output_id = self._persist_creator_output(planner_id, creator_results)

            reviewer_results = self._run_reviewer(creator_results)
            self._persist_review(creator_output_id, reviewer_results)

            image_result = self._run_image(creator_results, creator_output_id)

        package = {
            "run_id": run_id,
            "research": research_results,
            "planning": planner_results,
            "creation": creator_results,
            "review": reviewer_results,
            "image": image_result,
            "publish": None,
        }
        package_path = self._save_package(package)
        package["package_path"] = str(package_path)

        publish_result = self._run_publish(creator_output_id, package_path, package, run_id)
        package["publish"] = publish_result
        self._save_package(package, package_path)
        return package

    def _agents_setup(self) -> tuple[ResearchAgent, PlannerAgent, CreatorAgent, ReviewerAgent]:
        self._ensure_agents()
        return self.research_agent, self.planner_agent, self.creator_agent, self.reviewer_agent

    def _run_research(self) -> dict[str, Any]:
        research_agent = self._agents_setup()[0]
        return research_agent.execute(
            {
                "identity": "brain/identity.md",
                "strategy": "brain/strategy.md",
                "prompt": "research.md",
            }
        )

    def _run_planner(self, research_output: dict[str, Any]) -> dict[str, Any]:
        planner_agent = self._agents_setup()[1]
        return planner_agent.execute({"research_output": research_output})

    def _run_creator(self, planner_output: dict[str, Any]) -> dict[str, Any]:
        creator_agent = self._agents_setup()[2]
        return creator_agent.execute(
            {
                "selected_idea": planner_output["selected_idea"],
                "identity": "brain/identity.md",
                "constitution": "brain/constitution.md",
                "strategy": "brain/strategy.md",
            }
        )

    def _run_reviewer(self, creator_output: dict[str, Any]) -> dict[str, Any]:
        reviewer_agent = self._agents_setup()[3]
        return reviewer_agent.execute(
            {
                "creator_output": creator_output,
                "identity": "brain/identity.md",
                "constitution": "brain/constitution.md",
            }
        )

    def _run_image(self, creator_output: dict[str, Any], creator_output_id: int) -> dict[str, Any]:
        request = ImageRequest(
            prompt=creator_output["image_prompt"],
            brand_style="clean",
            aspect_ratio="1:1",
        )
        image_result = self.image_provider.generate(request)
        self._persist_image_asset(creator_output_id, image_result)
        return image_result.__dict__

    def _run_publish(
        self,
        creator_output_id: int,
        package_path: Path,
        package: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        if self.publisher.name == "instagram":
            image = package["image"]
            media_url = self._prepare_media(image, run_id)
            image["media_url"] = media_url
            self._save_package(package, package_path)

        result = self.publisher.publish(str(package_path))
        self._persist_publish_package(creator_output_id, result, package_path)

        output = result.__dict__
        if result.status == "published":
            post_id = self._persist_published_post(package, result)
            experiment_id = self._assign_to_active_experiment(post_id)
            output["post_id"] = post_id
            output["experiment_id"] = experiment_id
        return output

    def _prepare_media(self, image: dict[str, Any], run_id: str) -> str:
        settings = self.settings
        if settings.media_host == "github":
            if not settings.media_host_repo or not settings.media_host_token:
                raise MediaHostingError(
                    "MEDIA_HOST=github requires MEDIA_HOST_REPO and MEDIA_HOST_TOKEN"
                )
            jpeg_path = convert_to_jpeg(
                Path(image["file_path"]),
                Path("images") / "jpeg" / f"{run_id}.jpg",
            )
            host = GitHubRawImageHost(
                repo=settings.media_host_repo,
                token=settings.media_host_token,
                branch=settings.media_host_branch,
                base_path=settings.media_host_path,
            )
            hosted = host.upload(jpeg_path, f"{run_id}/{jpeg_path.name}")
            return hosted.url
        raise MediaHostingError(f"Unsupported MEDIA_HOST for Instagram publishing: {settings.media_host!r}")

    def _persist_planner_idea(self, planner_output: dict[str, Any], research_id: int) -> int:
        selected_idea = planner_output["selected_idea"]
        if isinstance(selected_idea, dict):
            idea_text = selected_idea.get("idea", str(selected_idea))
            educational_score = float(selected_idea.get("educational_score", 0.0))
            originality_score = float(selected_idea.get("originality_score", 0.0))
            engagement_score = float(selected_idea.get("engagement_score", 0.0))
            relevance_score = float(selected_idea.get("relevance_score", 0.0))
            total_score = selected_idea.get(
                "total_score",
                educational_score + originality_score + engagement_score + relevance_score,
            )
            reasoning = selected_idea.get("reasoning", "Selected by planner as the strongest content idea.")
        else:
            idea_text = str(selected_idea)
            educational_score = originality_score = engagement_score = relevance_score = 0.0
            total_score = 0.0
            reasoning = "Selected by planner as the strongest content idea."

        cursor = self.database.execute(
            "INSERT INTO planner_ideas(research_id, idea_text, educational_score, originality_score, engagement_score, relevance_score, total_score, selected, reasoning, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                research_id,
                idea_text,
                educational_score,
                originality_score,
                engagement_score,
                relevance_score,
                total_score,
                1,
                reasoning,
                utc_now_iso(),
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
                creator_output["alt_text"],
                "",
                "",
                utc_now_iso(),
            ),
        )
        return cursor.lastrowid

    def _persist_review(self, creator_output_id: int, reviewer_output: dict[str, Any]) -> int:
        cursor = self.database.execute(
            "INSERT INTO review_history(creator_output_id, status, feedback, timestamp) VALUES (?, ?, ?, ?)",
            (
                creator_output_id,
                reviewer_output["status"],
                json.dumps(reviewer_output["reasons"]),
                reviewer_output["timestamp"],
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
                utc_now_iso(),
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
                utc_now_iso(),
            ),
        )
        return cursor.lastrowid

    def _persist_published_post(self, package: dict[str, Any], publish_result: PublishResult) -> int:
        creation = package["creation"]
        research = package["research"]
        image = package["image"]
        cursor = self.database.execute(
            "INSERT INTO posts(external_id, caption, image_description, hashtags, topic, image_path, media_url, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                publish_result.published_id,
                creation["caption"],
                creation.get("alt_text", ""),
                json.dumps(creation.get("hashtags", [])),
                research.get("recommended_topic"),
                image.get("file_path"),
                image.get("media_url"),
                utc_now_iso(),
            ),
        )
        return cursor.lastrowid

    def _assign_to_active_experiment(self, post_id: int) -> int | None:
        active = self.experiments.list_active()
        if not active:
            return None
        experiment = active[0]
        control_count = len(self.experiments.posts_for_arm(experiment.id, "control"))
        variant_count = len(self.experiments.posts_for_arm(experiment.id, "variant"))
        arm = "variant" if variant_count < control_count else "control"
        self.experiments.assign_post(experiment.id, post_id, arm)
        logger.info("Assigned post %s to experiment %s (%s)", post_id, experiment.id, arm)
        return experiment.id

    def _save_package(self, package: dict[str, Any], path: Path | str | None = None) -> Path:
        output_dir = Path("posts")
        output_dir.mkdir(parents=True, exist_ok=True)
        if path is None:
            run_id = package.get("run_id") or uuid.uuid4().hex[:8]
            path = output_dir / f"publish_package_{run_id}.json"
        else:
            path = Path(path)
        path.write_text(json.dumps(package, indent=2, default=str), encoding="utf-8")
        return path

    def _success_body(self, package: dict[str, Any], run_id: str) -> str:
        research = package["research"]
        creation = package["creation"]
        publish = package.get("publish") or {}
        lines = [
            f"Run: {run_id}",
            f"Topic: {research.get('recommended_topic')}",
            f"Caption: {creation.get('caption', '')[:120]}",
            f"Publish status: {publish.get('status')}",
            f"Published id: {publish.get('published_id')}",
            f"Media URL: {(package.get('image') or {}).get('media_url', 'n/a')}",
        ]
        return "\n".join(lines)

    def _failure_body(self, error: Exception, run_id: str) -> str:
        return (
            f"Run: {run_id}\n"
            f"Stage: content pipeline\n"
            f"Error: {error}\n"
            "Suggested action: inspect logs; verify OPENCODE_COMMAND, image provider, "
            "media hosting (MEDIA_HOST), and Instagram credentials."
        )

    def close(self) -> None:
        if self._owns_database:
            self.database.close()
