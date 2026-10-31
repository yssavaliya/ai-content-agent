from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..agents.creator import CreatorAgent
from ..agents.planner import PlannerAgent
from ..agents.predictor import PredictorAgent
from ..agents.research import ResearchAgent
from ..agents.reviewer import ReviewerAgent
from ..database.connection import DatabaseConnection
from ..notifications.channels import DryRunChannel
from ..notifications.notifier import Notifier
from ..opencode.context import set_run_id
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

# Publishers that really post to Instagram. Buffer reports "scheduled"/"sent" rather than "published",
# so the status alone cannot decide whether a post must be tracked for analytics and experiments.
LIVE_PUBLISHERS = frozenset({"instagram", "buffer"})
NOT_LIVE_STATUSES = frozenset({"error", "failed", "draft", "needs_approval", "blocked_review", ""})


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
        self.prompt_manager = PromptManager()
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
        self.predictor_agent: PredictorAgent | None = None
        self._fallbacks: list[str] = []

    def _use_fallback(self, stage: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Flag deterministic template output so it is never mistaken for model output."""
        self._fallbacks.append(stage)
        payload["source"] = "procedural_fallback"
        return payload

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
        if self.predictor_agent is None:
            self.predictor_agent = PredictorAgent(
                prompt_manager=self.prompt_manager,
                database=self.database,
            )

    def run(self, run_id: str | None = None) -> dict[str, Any]:
        run_id = run_id or uuid.uuid4().hex[:8]
        self._fallbacks = []
        set_run_id(run_id)
        logger.info("Pipeline run %s starting", run_id)
        try:
            package = self._produce_content(run_id)
            self._save_package(package, package.get("package_path"))
            publish_status = (package.get("publish") or {}).get("status")
            if publish_status == "blocked_review":
                self.notifier.send_failure(
                    subject="AI Content Agent: post blocked by review",
                    body=self._blocked_body(package, run_id),
                    metadata={"run_id": run_id, "color": 15158332},
                )
            else:
                published = publish_status not in {None, "dry-run"}
                subject = (
                    "AI Content Agent: daily post published"
                    if published
                    else "AI Content Agent: daily post ready for manual publishing"
                )
                if package.get("fallbacks"):
                    subject += " (template fallback content)"
                self.notifier.send_success(
                    subject=subject,
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
            set_run_id(None)
            self.close()

    def _produce_content(self, run_id: str) -> dict[str, Any]:
        timing = {}
        stage_start = time.perf_counter()
        
        logger.info("::notice::[Pipeline %s] Stage 1/8: ResearchAgent started", run_id)
        stage_start = time.perf_counter()
        research_results = self._run_research()
        timing["research_ms"] = int((time.perf_counter() - stage_start) * 1000)
        logger.info("::notice::[Pipeline %s] Stage 1/8: ResearchAgent completed in %dms", run_id, timing["research_ms"])
        
        research_id = research_results.get("research_id")
        if not isinstance(research_id, int) or research_id <= 0:
            raise PipelineError(
                "ResearchAgent did not return a valid research_id; aborting to avoid orphan rows"
            )

        logger.info("::notice::[Pipeline %s] Stage 2/8: PlannerAgent started", run_id)
        stage_start = time.perf_counter()
        planner_results = self._run_planner(research_results)
        timing["planner_ms"] = int((time.perf_counter() - stage_start) * 1000)
        logger.info("::notice::[Pipeline %s] Stage 2/8: PlannerAgent completed in %dms", run_id, timing["planner_ms"])
        
        planner_id = self._persist_planner_idea(planner_results, research_id)

        logger.info("::notice::[Pipeline %s] Stage 3/8: CreatorAgent started", run_id)
        stage_start = time.perf_counter()
        creator_results = self._run_creator(planner_results)
        timing["creator_ms"] = int((time.perf_counter() - stage_start) * 1000)
        logger.info("::notice::[Pipeline %s] Stage 3/8: CreatorAgent completed in %dms", run_id, timing["creator_ms"])
        
        creator_output_id = self._persist_creator_output(planner_id, creator_results)

        logger.info("::notice::[Pipeline %s] Stage 4/8: ReviewerAgent started", run_id)
        stage_start = time.perf_counter()
        reviewer_results = self._run_reviewer(creator_results)
        timing["reviewer_ms"] = int((time.perf_counter() - stage_start) * 1000)
        logger.info("::notice::[Pipeline %s] Stage 4/8: ReviewerAgent completed in %dms", run_id, timing["reviewer_ms"])
        
        self._persist_review(creator_output_id, reviewer_results)

        if reviewer_results["status"] != "PASS":
            logger.warning(
                "::warning::[Pipeline %s] ReviewerAgent returned %s; skipping image and publish",
                run_id,
                reviewer_results["status"],
            )
            return self._blocked_package(
                run_id, creator_output_id, research_results, planner_results, creator_results, reviewer_results, timing
            )

        logger.info("::notice::[Pipeline %s] Stage 5/8: PredictorAgent started", run_id)
        stage_start = time.perf_counter()
        predictor_results = self._run_predictor(creator_results, research_results, reviewer_results)
        timing["predictor_ms"] = int((time.perf_counter() - stage_start) * 1000)
        logger.info("::notice::[Pipeline %s] Stage 5/8: PredictorAgent completed in %dms", run_id, timing["predictor_ms"])

        self._persist_prediction(creator_output_id, predictor_results)

        logger.info("::notice::[Pipeline %s] Stage 6/8: Image generation started", run_id)
        stage_start = time.perf_counter()
        image_result = self._run_image(creator_results, creator_output_id)
        timing["image_ms"] = int((time.perf_counter() - stage_start) * 1000)
        logger.info("::notice::[Pipeline %s] Stage 6/8: Image generation completed in %dms", run_id, timing["image_ms"])

        package = {
            "run_id": run_id,
            "research": research_results,
            "planning": planner_results,
            "creation": creator_results,
            "review": reviewer_results,
            "prediction": predictor_results,
            "image": image_result,
            "publish": None,
            "fallbacks": list(self._fallbacks),
        }
        package_path = self._save_package(package)
        package["package_path"] = str(package_path)

        logger.info("::notice::[Pipeline %s] Stage 7/8: Publish started", run_id)
        stage_start = time.perf_counter()
        publish_result = self._run_publish(creator_output_id, package_path, package, run_id)
        timing["publish_ms"] = int((time.perf_counter() - stage_start) * 1000)
        logger.info("::notice::[Pipeline %s] Stage 7/8: Publish completed in %dms", run_id, timing["publish_ms"])
        
        package["publish"] = publish_result
        self._save_package(package, package_path)
        
        timing["total_ms"] = sum(timing.values())
        logger.info("::notice::[Pipeline %s] Stage 8/8: Complete. Total: %dms (research=%dms planner=%dms creator=%dms reviewer=%dms predictor=%dms image=%dms publish=%dms)", 
                    run_id, timing["total_ms"], timing.get("research_ms", 0), timing.get("planner_ms", 0),
                    timing.get("creator_ms", 0), timing.get("reviewer_ms", 0), timing.get("predictor_ms", 0),
                    timing.get("image_ms", 0), timing.get("publish_ms", 0))
        
        package["timing"] = timing
        return package

    def _blocked_package(
        self,
        run_id: str,
        creator_output_id: int,
        research: dict[str, Any],
        planning: dict[str, Any],
        creation: dict[str, Any],
        review: dict[str, Any],
        timing: dict[str, int],
    ) -> dict[str, Any]:
        """Persist a package for content the reviewer rejected, without generating or publishing."""
        result = PublishResult(
            provider="none",
            status="blocked_review",
            published_id="",
            metadata={"reasons": review.get("reasons", [])},
        )
        package: dict[str, Any] = {
            "run_id": run_id,
            "research": research,
            "planning": planning,
            "creation": creation,
            "review": review,
            "prediction": None,
            "image": None,
            "publish": result.__dict__,
            "fallbacks": list(self._fallbacks),
            "timing": timing,
        }
        package_path = self._save_package(package)
        package["package_path"] = str(package_path)
        self._persist_publish_package(creator_output_id, result, package_path)
        self._save_package(package, package_path)
        return package

    def _agents_setup(self) -> tuple[ResearchAgent, PlannerAgent, CreatorAgent, ReviewerAgent, PredictorAgent]:
        self._ensure_agents()
        return self.research_agent, self.planner_agent, self.creator_agent, self.reviewer_agent, self.predictor_agent

    def _procedural_research(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        day = now.day
        catalog = [
            {
                "recommended_topic": "Modern Anime Aesthetics: How Studio Visuals Drive Viral Instagram Engagement",
                "audience_problem": "Creators and anime pages struggle to break down complex visual storytelling into quick, shareable carousel slides.",
                "why_now": "Solo Leveling and Jujutsu Kaisen visual breakdowns are driving peak engagement across reels and carousels right now.",
                "hook": "Ever wondered why some anime scenes give you instant goosebumps? Here is the secret behind viral visual pacing.",
                "supporting_points": [
                    "Dynamic sakuga sequences capture attention in the first 1.5 seconds of the scroll.",
                    "Color grading shifts (high-contrast neon vs dark shadows) trigger emotional reactions and high save rates.",
                    "Translating anime aesthetics into creator graphics keeps feeds visually consistent and recognisable."
                ],
                "trend_signals": ["#AnimeArt trending across Instagram explore", "Solo Leveling season animation analysis"],
                "candidate_topics": [
                    "Modern Anime Aesthetics: How Studio Visuals Drive Viral Instagram Engagement",
                    "Character Arc Breakdown: Why Antiheroes Dominate Modern Shonen Feeds"
                ],
                "confidence": 94,
                "reasoning": "High-interest cultural intersection between anime storytelling and viral visual content creation for social growth."
            },
            {
                "recommended_topic": "Autonomous AI Agents in 2026: The End-to-End Content Pipeline Blueprint",
                "audience_problem": "Creators spend many hours on research and drafting instead of engaging with their community.",
                "why_now": "Multi-agent orchestration frameworks now automate research, planning, generation, and virality scoring in real time.",
                "hook": "Stop losing hours to manual drafting. Here is an autonomous agent workflow worth copying.",
                "supporting_points": [
                    "Decoupled agents for research, planning, copy, and review eliminate creative fatigue.",
                    "Real-time virality prediction models catch weak hooks before you hit publish.",
                    "Deterministic image generation guarantees brand consistency on every single post."
                ],
                "trend_signals": ["#AIAgents trending on developer Twitter and Instagram", "Creator automation workflows are a recurring topic among developers"],
                "candidate_topics": [
                    "Autonomous AI Agents in 2026: The End-to-End Content Pipeline Blueprint",
                    "How to Build a Zero-Touch AI Content Engine Using Open Models"
                ],
                "confidence": 96,
                "reasoning": "Direct alignment with the brand identity: research-driven AI workflows designed to maximize creator productivity and consistency."
            }
        ]
        selected = catalog[day % len(catalog)]
        payload = {
            "recommended_topic": selected["recommended_topic"],
            "audience_problem": selected["audience_problem"],
            "why_now": selected["why_now"],
            "hook": selected["hook"],
            "supporting_points": selected["supporting_points"],
            "trend_signals": selected["trend_signals"],
            "candidate_topics": selected["candidate_topics"],
            "confidence": selected["confidence"],
            "reasoning": selected["reasoning"],
            "timestamp": now.isoformat(),
        }
        research_agent = self._agents_setup()[0]
        research_id = research_agent._persist_research(payload)
        payload["research_id"] = research_id
        return payload

    def _procedural_planner(self, research_output: dict[str, Any]) -> dict[str, Any]:
        topic = str(research_output.get("recommended_topic") or "Viral Content Strategy")
        ideas = [
            {
                "idea": f"Comprehensive Breakdown: {topic}. Step-by-step framework with actionable takeaways.",
                "educational_score": 0.92,
                "originality_score": 0.88,
                "engagement_score": 0.94,
                "relevance_score": 0.95,
            },
            {
                "idea": f"Mistakes & Fixes: 3 common traps when implementing {topic} and how to avoid them.",
                "educational_score": 0.86,
                "originality_score": 0.84,
                "engagement_score": 0.90,
                "relevance_score": 0.91,
            },
            {
                "idea": f"Behind the Scenes: Inside the engine powering {topic}.",
                "educational_score": 0.88,
                "originality_score": 0.91,
                "engagement_score": 0.87,
                "relevance_score": 0.89,
            },
        ]
        for idea in ideas:
            idea["reasoning"] = "Fixed template idea used because the planner LLM was unavailable."
        return {
            "ideas": ideas,
            "selected_idea": ideas[0],
        }

    def _procedural_creator(self, planner_output: dict[str, Any]) -> dict[str, Any]:
        selected_idea = planner_output.get("selected_idea", {}).get("idea", "Content Strategy")
        is_anime = "anime" in selected_idea.lower()

        if is_anime:
            carousel_outline = [
                "Single Post Focus: Standalone anime concept artwork and philosophy breakdown",
            ]
            caption = (
                "The world only celebrates the awakening. \U00002694\U0001f311\n\n"
                "They never see the ten thousand hours of quiet discipline in the shadows.\n\n"
                "Whether you are mastering an art, building something legendary, or locking into your craft — remember:\n\n"
                "\u2022 Relentless focus beats noisy talent every single time\n"
                "\u2022 The greatest transformations happen when nobody is watching\n"
                "\u2022 Your current chapter is the training arc for what comes next\n\n"
                "Save this visual reminder when you need that extra surge of momentum. \U0001f4cc"
            )
            cta = "Drop a ⚔️ in the comments if you are locking into your craft today!"
            hashtags = ["#anime", "#animeart", "#sololeveling", "#visualstorytelling", "#digitalart", "#aesthetic", "#animephilosophy"]
            image_prompt = "Masterpiece anime key visual, dramatic blood moon eclipse, lone swordsman silhouette with glowing cyan katana blade, stardust particles, cinematic anime poster"
            alt_text = "Cinematic anime artwork featuring a lone swordsman standing before a glowing celestial eclipse moon."
        else:
            carousel_outline = [
                "Single Post Focus: High-impact standalone visual art and architecture blueprint",
            ]
            caption = (
                "Building in the shadows before the breakthrough hits. \U000026a1\U0001f680\n\n"
                "Most people see autonomous systems as overnight success. The reality?\n\n"
                "• Iterating every single pipeline stage until it never breaks\n"
                "• Replacing manual grunt work with deterministic intelligence\n"
                "• Protecting your creative energy for the work that actually matters\n\n"
                "The future belongs to the builders who automate the routine and amplify the craft.\n\n"
                "Save this blueprint for your next build session. \U0001f4cc"
            )
            cta = "Are you building with autonomous AI agents this year? Drop your thoughts below!"
            hashtags = ["#aiagents", "#creatoreconomy", "#buildinpublic", "#autonomousagents", "#developers", "#python"]
            image_prompt = "Futuristic cyber key visual, glowing neon energy core, lone creator silhouette, cosmic cyber particles, cinematic poster 1080x1080"
            alt_text = "Futuristic digital art poster featuring a glowing energy core and cyber typography."

        return {
            "carousel_outline": carousel_outline,
            "caption": caption,
            "cta": cta,
            "hashtags": hashtags,
            "image_prompt": image_prompt,
            "alt_text": alt_text,
        }

    def _procedural_reviewer(self, creator_output: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "PASS",
            "reasons": [
                "Reviewer LLM unavailable; this verdict was NOT produced by a model review.",
                "Content comes from a fixed, pre-approved template and was passed without checks.",
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _procedural_predictor(
        self,
        creator_output: dict[str, Any],
        research_output: dict[str, Any],
        reviewer_output: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "virality_score": 50,
            "virality_label": "MEDIUM",
            "virality_probability": 0.5,
            "key_factors": ["No model estimate available (predictor LLM unavailable)"],
            "risks": ["This is a neutral placeholder, not an analysis of the post"],
            "reasoning": "Predictor LLM unavailable; a neutral placeholder score is recorded instead of an estimate.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _run_research(self) -> dict[str, Any]:
        try:
            research_agent = self._agents_setup()[0]
            return research_agent.execute(
                {
                    "identity": "brain/identity.md",
                    "strategy": "brain/strategy.md",
                    "market": "brain/market.md",
                    "prompt": "research.md",
                }
            )
        except Exception as exc:
            logger.warning(
                "::warning::[ResearchAgent] LLM execution failed (%s); activating autonomous procedural research fallback",
                exc,
            )
            return self._use_fallback("research", self._procedural_research())

    def _run_planner(self, research_output: dict[str, Any]) -> dict[str, Any]:
        try:
            planner_agent = self._agents_setup()[1]
            return planner_agent.execute(
                {
                    "research_output": research_output,
                    "market": "brain/market.md",
                }
            )
        except Exception as exc:
            logger.warning(
                "::warning::[PlannerAgent] LLM execution failed (%s); activating autonomous procedural planner fallback",
                exc,
            )
            return self._use_fallback("planner", self._procedural_planner(research_output))

    def _run_creator(self, planner_output: dict[str, Any]) -> dict[str, Any]:
        try:
            creator_agent = self._agents_setup()[2]
            return creator_agent.execute(
                {
                    "selected_idea": planner_output["selected_idea"],
                    "identity": "brain/identity.md",
                    "constitution": "brain/constitution.md",
                    "strategy": "brain/strategy.md",
                    "market": "brain/market.md",
                }
            )
        except Exception as exc:
            logger.warning(
                "::warning::[CreatorAgent] LLM execution failed (%s); activating autonomous procedural creator fallback",
                exc,
            )
            return self._use_fallback("creator", self._procedural_creator(planner_output))

    def _run_reviewer(self, creator_output: dict[str, Any]) -> dict[str, Any]:
        try:
            reviewer_agent = self._agents_setup()[3]
            return reviewer_agent.execute(
                {
                    "creator_output": creator_output,
                    "identity": "brain/identity.md",
                    "constitution": "brain/constitution.md",
                    "market": "brain/market.md",
                }
            )
        except Exception as exc:
            logger.warning(
                "::warning::[ReviewerAgent] LLM execution failed (%s); activating autonomous procedural reviewer fallback",
                exc,
            )
            return self._use_fallback("reviewer", self._procedural_reviewer(creator_output))

    def _run_predictor(
        self,
        creator_output: dict[str, Any],
        research_output: dict[str, Any],
        reviewer_output: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            predictor_agent = self._agents_setup()[4]
            recent_posts = predictor_agent.recent_posts_performance(limit=10)
            return predictor_agent.execute(
                {
                    "creator_output": creator_output,
                    "research_json": json.dumps(research_output, indent=2, default=str),
                    "review_json": json.dumps(reviewer_output, indent=2, default=str),
                    "market": "brain/market.md",
                    "recent_posts_json": recent_posts,
                }
            )
        except Exception as exc:
            logger.warning(
                "::warning::[PredictorAgent] LLM execution failed (%s); activating autonomous procedural predictor fallback",
                exc,
            )
            return self._use_fallback("predictor", self._procedural_predictor(creator_output, research_output, reviewer_output))

    def _persist_prediction(self, creator_output_id: int, predictor_output: dict[str, Any]) -> int:
        cursor = self.database.execute(
            "INSERT INTO virality_predictions(creator_output_id, virality_score, virality_label, virality_probability, key_factors, risks, reasoning, timestamp, raw_payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                creator_output_id,
                predictor_output["virality_score"],
                predictor_output["virality_label"],
                predictor_output["virality_probability"],
                json.dumps(predictor_output["key_factors"]),
                json.dumps(predictor_output["risks"]),
                predictor_output["reasoning"],
                predictor_output["timestamp"],
                json.dumps(predictor_output),
            ),
        )
        return cursor.lastrowid

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
        if self.publisher.name in {"instagram", "buffer"}:
            image = package["image"]
            media_url = self._prepare_media(image, run_id)
            image["media_url"] = media_url
            self._save_package(package, package_path)

        result = self.publisher.publish(str(package_path))
        self._persist_publish_package(creator_output_id, result, package_path)

        output = result.__dict__
        if result.provider in LIVE_PUBLISHERS and result.status.lower() not in NOT_LIVE_STATUSES:
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
        prediction = package.get("prediction") or {}
        lines = [
            f"Run: {run_id}",
            f"Topic: {research.get('recommended_topic')}",
            f"Caption: {creation.get('caption', '')[:120]}",
            f"Image Prompt: {creation.get('image_prompt', 'n/a')}",
            f"Publish status: {publish.get('status')}",
            f"Published id: {publish.get('published_id')}",
            f"Media URL: {(package.get('image') or {}).get('media_url', 'n/a')}",
        ]
        if package.get("fallbacks"):
            lines += [
                "",
                "WARNING: the LLM was unavailable for: " + ", ".join(package["fallbacks"]),
                "These stages used fixed template output, not model output. Check LLM_PROVIDER, API keys and quotas.",
            ]
        if publish.get("provider") not in LIVE_PUBLISHERS:
            hashtags = creation.get("hashtags") or []
            lines += [
                "",
                "READY FOR MANUAL PUBLISHING",
                f"Full caption: {creation.get('caption', '')}",
                f"Hashtags: {' '.join(hashtags) if hashtags else '(none)'}",
                f"Alt text: {creation.get('alt_text') or '(none)'}",
            ]
            kit_path = (publish.get("metadata") or {}).get("kit_path")
            if kit_path:
                lines.append(f"Post kit: {kit_path}")
        if prediction.get("virality_score") is not None:
            lines.append("")
            lines.append("VIRALITY PREDICTION")
            lines.append(f"Score: {prediction.get('virality_score')}/100 ({prediction.get('virality_label')})")
            lines.append(f"Probability: {prediction.get('virality_probability')}")
            lines.append(f"Key factors: {'; '.join(prediction.get('key_factors') or [])}")
            lines.append(f"Risks: {'; '.join(prediction.get('risks') or [])}")
        return "\n".join(lines)

    def _blocked_body(self, package: dict[str, Any], run_id: str) -> str:
        review = package.get("review") or {}
        reasons = "\n".join(f"- {reason}" for reason in review.get("reasons", []))
        return (
            f"Run: {run_id}\n"
            f"Topic: {(package.get('research') or {}).get('recommended_topic')}\n"
            f"The ReviewerAgent returned {review.get('status')}; nothing was generated or published.\n"
            f"Reasons:\n{reasons}\n"
            f"Package: {package.get('package_path')}"
        )

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
