from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from ..opencode.client import OpenCodeClient, extract_json_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnimeConcept:
    title: str
    genre: str
    synopsis: str
    setting: str
    target_audience: str
    visual_style: str
    themes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AnimeScene:
    scene_number: int
    location: str
    summary: str
    dialogue: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class AnimeStoryOutline:
    episode_number: int
    episode_title: str
    concept_title: str
    scenes: list[AnimeScene]
    cliffhanger: str


class AnimeContentGenerator:
    """Generates structured anime concepts, characters, episode scripts, and visual prompts."""

    def __init__(self, opencode_client: OpenCodeClient | None = None) -> None:
        self.client = opencode_client

    def generate_concept(self, theme: str, target_audience: str = "Shonen / Indian Anime Community") -> AnimeConcept:
        """Generate an original anime concept based on a theme and target audience."""
        if not theme.strip():
            raise ValueError("Theme must not be empty")

        if self.client:
            prompt = (
                f"You are an anime director and showrunner. Create an original anime concept based on theme: '{theme}'.\n"
                f"Target audience: {target_audience}.\n"
                "Return ONLY a JSON object with this exact structure:\n"
                "{\n"
                '  "title": "Anime Title",\n'
                '  "genre": "Genre(s)",\n'
                '  "synopsis": "Engaging 2-3 sentence synopsis",\n'
                '  "setting": "Detailed world and era description",\n'
                '  "target_audience": "Target demographic",\n'
                '  "visual_style": "Color palette, animation style, and mood",\n'
                '  "themes": ["Theme 1", "Theme 2"]\n'
                "}\n"
            )
            try:
                res = self.client.run([], input_text=prompt, label="AnimeDirectorConcept")
                raw = extract_json_text(res.stdout)
                data = json.loads(raw)
                return AnimeConcept(
                    title=str(data["title"]),
                    genre=str(data["genre"]),
                    synopsis=str(data["synopsis"]),
                    setting=str(data["setting"]),
                    target_audience=str(data.get("target_audience", target_audience)),
                    visual_style=str(data["visual_style"]),
                    themes=list(data.get("themes", [theme])),
                )
            except Exception as exc:
                logger.warning("LLM generation failed for anime concept (%s); using procedural fallback", exc)

        clean_theme = theme.title()
        return AnimeConcept(
            title=f"Kage no Shinkaron: {clean_theme}",
            genre="Supernatural Sci-Fi / Action",
            synopsis=(
                f"In a world reshaped by {clean_theme.lower()}, an ordinary student awakens an ancient astral resonance "
                "that connects past civilizations with future quantum realities, challenging the sovereign order."
            ),
            setting="Neo-Varanasi, Year 2099 — towering bioluminescent spires built over ancient sacred rivers.",
            target_audience=target_audience,
            visual_style="Vibrant neon and deep indigo contrast, fluid kinetic sakuga action, high-key lighting.",
            themes=[clean_theme, "Destiny vs Free Will", "Technological Ascension"],
        )

    def generate_characters(self, concept: AnimeConcept, count: int = 2) -> list[dict[str, Any]]:
        """Generate cohesive characters for an anime concept."""
        if count < 1:
            raise ValueError("Character count must be at least 1")

        if self.client:
            prompt = (
                f"Generate {count} detailed characters for the anime concept:\n"
                f"Title: {concept.title}\nGenre: {concept.genre}\nSetting: {concept.setting}\n"
                "Return ONLY a JSON array of objects:\n"
                "[\n"
                "  {\n"
                '    "name": "Character Name",\n'
                '    "role": "Protagonist / Deuteragonist / Antagonist",\n'
                '    "personality": "Detailed personality traits",\n'
                '    "appearance": "Visual design, hair, eyes, costume",\n'
                '    "motivation": "Core driving goal",\n'
                '    "relationship_to_protagonist": "Dynamic with lead"\n'
                "  }\n"
                "]\n"
            )
            try:
                res = self.client.run([], input_text=prompt, label="AnimeCharacterCreator")
                raw = extract_json_text(res.stdout)
                characters = json.loads(raw)
                if isinstance(characters, list) and len(characters) >= count:
                    return characters[:count]
            except Exception as exc:
                logger.warning("LLM character generation failed (%s); using procedural fallback", exc)

        chars = [
            {
                "name": "Ren Kusanagi",
                "role": "Protagonist",
                "personality": "Determined, observant, fiercely loyal, harboring quiet doubt.",
                "appearance": "Dark silver hair, glowing amber cyber-iris, midnight blue tactical coat.",
                "motivation": f"Uncover the truth behind the {concept.themes[0] if concept.themes else 'phenomenon'}.",
                "relationship_to_protagonist": "Self",
            },
            {
                "name": "Meera 'Cipher' Sen",
                "role": "Deuteragonist",
                "personality": "Brilliant quantum archivist, quick-witted, skeptical of dogma.",
                "appearance": "Crimson cropped hair, holographic spectacles, embroidered high-collar cowl.",
                "motivation": "Protect ancient collective memory from corporate erasure.",
                "relationship_to_protagonist": "Trusted ally and strategic advisor.",
            },
        ]
        return chars[:count]

    def generate_episode_outline(
        self,
        concept: AnimeConcept,
        characters: list[dict[str, Any]],
        episode_number: int = 1,
    ) -> AnimeStoryOutline:
        """Generate a coherent episode outline with scenes and dramatic dialogue."""
        lead_name = characters[0]["name"] if characters else "Protagonist"
        ally_name = characters[1]["name"] if len(characters) > 1 else "Ally"

        scenes = [
            AnimeScene(
                scene_number=1,
                location=f"{concept.setting} - Rooftop Atrium",
                summary=f"{lead_name} witnesses an unusual spatial fluctuation during the midnight cycle.",
                dialogue=[
                    {"speaker": lead_name, "line": "The sky shouldn't be fracturing like this. Not here."},
                    {"speaker": ally_name, "line": "The readings match the forbidden frequency, Ren. It's begun."},
                ],
            ),
            AnimeScene(
                scene_number=2,
                location="Subterranean Archive Chambers",
                summary="The duo decodes the origin frequency while evading sovereign enforcers.",
                dialogue=[
                    {"speaker": ally_name, "line": "If they breach the firewall before we synchronize, everything resets."},
                    {"speaker": lead_name, "line": "Then I won't let them take a single step further."},
                ],
            ),
            AnimeScene(
                scene_number=3,
                location="The Resonance Core",
                summary=f"{lead_name} unlocks the primary power node, releasing a radiant wave that sweeps the district.",
                dialogue=[
                    {"speaker": lead_name, "line": "I see it now... the tomorrow we were meant to build!"},
                ],
            ),
        ]

        cliffhanger = f"As the energy surge subsides, a shadowy vanguard emerges from the rift bearing the crest of {lead_name}'s lost lineage."

        return AnimeStoryOutline(
            episode_number=episode_number,
            episode_title=f"Episode {episode_number}: Awakening of the Resonance",
            concept_title=concept.title,
            scenes=scenes,
            cliffhanger=cliffhanger,
        )

    def generate_post_package(
        self,
        concept: AnimeConcept,
        outline: AnimeStoryOutline,
        characters: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Convert concept, characters, and outline into an Instagram publish-ready post package."""
        lead_char = characters[0] if characters else {"name": "Protagonist", "appearance": "Anime warrior"}

        carousel_outline = [
            f"Slide 1 (Cover): '{concept.title}' — The anime concept India has been waiting for.",
            f"Slide 2 (The Hook): {concept.synopsis}",
            f"Slide 3 (The Protagonist): Meet {lead_char['name']} — {lead_char['personality']}",
            f"Slide 4 (Episode 1 Breakdown): {outline.episode_title} — key turning points.",
            f"Slide 5 (The Cliffhanger): {outline.cliffhanger}",
            "Slide 6 (Community Call): Would you binge-watch this on day one? Drop your thoughts below!",
        ]

        caption = (
            f"Agar ye anime release hota toh pehle din dekhoge? 🔥\n\n"
            f"Concept: '{concept.title}' ({concept.genre})\n"
            f"{concept.synopsis}\n\n"
            f"Lead Character: {lead_char['name']} | Setting: {concept.setting}\n\n"
            f"Drop a ❤️ if you want an animated pilot episode! Tell us your dream voice cast in comments 👇"
        )

        image_prompt = (
            f"Masterpiece cinematic anime key visual for '{concept.title}', {concept.visual_style}, "
            f"featuring {lead_char['name']}, {lead_char['appearance']}, standing heroically against {concept.setting}, "
            "dramatic lighting, vibrant cel-shaded anime aesthetic, high-octane composition, 8k resolution, artstation trending."
        )

        alt_text = f"Anime key visual artwork for {concept.title} featuring {lead_char['name']} in a dramatic setting."

        return {
            "concept": asdict(concept),
            "characters": characters,
            "outline": {
                "episode_number": outline.episode_number,
                "episode_title": outline.episode_title,
                "cliffhanger": outline.cliffhanger,
                "scenes_count": len(outline.scenes),
            },
            "carousel_outline": carousel_outline,
            "caption": caption,
            "cta": "Tell us your dream Hindi/Japanese voice cast in the comments!",
            "hashtags": [
                "#animeindia",
                "#animelovers",
                "#animeconcept",
                "#otakubharat",
                "#shonen",
                "#animeart",
                "#desiotaku",
                "#animefandom",
            ],
            "image_prompt": image_prompt,
            "alt_text": alt_text,
        }
