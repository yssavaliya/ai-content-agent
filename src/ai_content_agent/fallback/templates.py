"""Offline post generator used when every LLM provider fails.

Pure Python, no network, deterministic for a given (seed, theme, variant). It combines pools of
hand-written lines (hooks, bullets, closers, calls to action, image prompt parts) so each day's post differs
and the duplicate guard can ask for another ``variant`` when a combination was already used. The lines
contain no statistics or factual claims, so nothing here can be wrong about the world.
"""

from __future__ import annotations

import random
from typing import Any

THEMES = ("anime", "ai")

HOOKS = {
    "anime": [
        "Nobody applauds the training arc. Everybody remembers the finale.",
        "The hero you admire was once someone who refused to quit on an ordinary Tuesday.",
        "Power-ups are loud. Discipline is quiet. Only one of them lasts.",
        "Every legendary blade was folded a thousand times before it ever shone.",
        "Your next level is hiding inside the boring reps.",
        "Talent starts the story. Consistency writes the ending.",
        "The strongest character in the series is rarely the loudest.",
        "Plot armor does not exist off-screen. Preparation does.",
        "Before the awakening, there was a year nobody filmed.",
        "Mastery looks like repetition from the outside.",
        "The final form is built in the chapters nobody skips to.",
        "Even the fastest swordsman had to learn how to stand still.",
    ],
    "ai": [
        "The best system is the one that keeps shipping while you sleep.",
        "Automation does not replace craft. It protects the time you need for it.",
        "A small pipeline that runs every day beats a perfect one that never launches.",
        "Build the boring machine first. Creativity needs something reliable underneath it.",
        "Good tools remove friction. Great builders remove excuses.",
        "Consistency is a feature you have to engineer.",
        "Ship the first version before it feels ready.",
        "Your workflow is a story. Edit the slow chapters.",
        "Every reliable system started as an ugly prototype.",
        "Fewer moving parts, more finished work.",
    ],
}

BULLETS = {
    "anime": [
        "Relentless focus beats noisy talent every single time",
        "The biggest transformations happen when nobody is watching",
        "Your current chapter is the training arc for what comes next",
        "Small daily reps compound into the power-up everyone notices",
        "Rest is part of the training, not a break from it",
        "Comparison ends the arc early; patience keeps it going",
        "Finish the boring part first and the exciting part gets easier",
        "A clear goal turns random effort into real progress",
        "Setbacks are plot, not the end of the story",
        "Show up on the days you do not feel like the main character",
        "Protect your focus like it is your most valuable technique",
        "Progress you can measure is progress you can repeat",
        "One honest hour beats five distracted ones",
        "The craft gets lighter once the habit gets heavier",
        "Learn from the villains you lose to",
        "Make the next step so small it cannot be skipped",
        "Quiet consistency is its own kind of loud",
        "Let your work speak first and your results speak last",
    ],
    "ai": [
        "Automate the repeatable parts so your attention goes to the creative ones",
        "Measure what you publish and let the results steer the next idea",
        "Keep every step small, testable and easy to replace",
        "Write down what worked so the system can learn from it",
        "Reliability first, cleverness second",
        "Version your ideas the way you version your code",
        "A boring checklist saves more time than a clever shortcut",
        "Review the output, not just the process",
        "Fail loudly, recover quietly",
        "Start with one workflow and make it dependable",
        "Fewer tools, used well, beat a crowded stack",
        "Document the decision, not only the result",
        "Test the unhappy path before it finds you in production",
        "Iterate in public and keep the feedback loop short",
    ],
}

CLOSERS = [
    "Save this for the day motivation runs out. 📌",
    "Keep this where you will see it on a slow day. 📌",
    "Send this to someone in the middle of their own training arc.",
    "Save this as a reminder for your next session. 📌",
    "Come back to this when the work gets quiet.",
    "Share it with the person who keeps showing up.",
    "Screenshot this for the next time you doubt the process.",
    "Bookmark this and look again in a month. 📌",
]

CTAS = {
    "anime": [
        "Drop a ⚔️ if you are locking into your craft today.",
        "Comment the one habit you are building this month.",
        "Tell us your current training arc in one word.",
        "Save this and tag a friend who never skips the reps.",
        "Which line hit hardest? Reply with its number.",
        "Reply with the skill you are leveling up right now.",
        "Share your next small step in the comments.",
    ],
    "ai": [
        "What is the one task you would automate first? Tell us below.",
        "Save this and tag a builder who ships every day.",
        "Comment the tool you could not work without.",
        "Which line would you put on your desk? Reply with its number.",
        "Share the smallest improvement you made this week.",
        "Reply with the workflow you are building right now.",
    ],
}

EMOJI = ["⚔️🌑", "✨🌌", "🔥🗡️", "🌙⚡", "🌅🔥", "🗡️✨", "⚡🌌"]

HASHTAGS_BASE = ["#aimagix", "#animeart", "#digitalart"]
HASHTAGS_POOL = {
    "anime": [
        "#anime", "#animephilosophy", "#visualstorytelling", "#aiart", "#conceptart", "#cinematic",
        "#darkaesthetic", "#animeedit", "#motivation", "#discipline", "#mindset", "#sololeveling",
    ],
    "ai": [
        "#aiagents", "#automation", "#buildinpublic", "#creatoreconomy", "#python", "#opensource",
        "#workflow", "#productivity", "#aiart", "#developers", "#makers", "#indiehackers",
    ],
}

SUBJECTS = {
    "anime": [
        "lone swordsman silhouette holding a glowing cyan katana",
        "hooded wanderer carrying a lantern of blue fire",
        "armored guardian kneeling before an ancient gate",
        "young mage standing on a floating stone platform",
        "samurai in a rain-soaked alley with a single paper lantern",
        "cloaked traveler climbing a ruined spiral staircase",
        "masked archer on a cliff edge at dawn",
        "robed monk meditating beneath a storm of falling cherry blossoms",
    ],
    "ai": [
        "lone creator silhouette facing a wall of glowing holographic screens",
        "engineer in a long coat standing beside a floating neon core",
        "robed figure conducting streams of light like an orchestra",
        "android sculptor shaping a glowing sphere of data",
        "traveler crossing a bridge made of luminous circuit lines",
        "pilot at the helm of a ship steering through a data storm",
    ],
}

ENVIRONMENTS = {
    "anime": [
        "ruined temple above a sea of clouds",
        "mountain pass under a blood-red eclipse",
        "flooded city street reflecting a violet sky",
        "endless stairway carved into a glacier",
        "star-filled desert with floating monoliths",
        "pine forest wrapped in drifting embers",
        "obsidian canyon split by a river of light",
    ],
    "ai": [
        "futuristic control room with floating panels",
        "rooftop above a neon megacity at night",
        "vast server hall lit by blue light",
        "orbital station overlooking a glowing planet",
        "quiet workshop filled with holographic blueprints",
    ],
}

LIGHTING = [
    "deep violet and obsidian palette with vibrant cyan rim lighting",
    "golden hour backlight with drifting dust",
    "cold moonlight with warm ember highlights",
    "magenta and teal neon glow with volumetric fog",
    "pale dawn gradient with long dramatic shadows",
]

QUALITY_TAGS = (
    "masterpiece anime key visual, volumetric lighting, glowing embers, cinematic composition, "
    "octane render, 8k resolution, sharp focus, no text, no watermark"
)


def generate_post(theme: str, seed: str, variant: int = 0) -> dict[str, Any]:
    """Build one post for ``theme`` ('anime' or 'ai'). Same (seed, theme, variant) gives the same post."""
    if theme not in THEMES:
        raise ValueError(f"Unknown theme {theme!r}; expected one of {THEMES}")
    rng = random.Random(f"{seed}|{theme}|{variant}")

    hook = rng.choice(HOOKS[theme])
    bullets = rng.sample(BULLETS[theme], 3)
    closer = rng.choice(CLOSERS)
    cta = rng.choice(CTAS[theme])
    caption = (
        f"{hook} {rng.choice(EMOJI)}\n\n"
        + "\n".join(f"• {bullet}" for bullet in bullets)
        + f"\n\n{closer}"
    )
    hashtags = HASHTAGS_BASE + rng.sample(HASHTAGS_POOL[theme], 5)

    subject = rng.choice(SUBJECTS[theme])
    environment = rng.choice(ENVIRONMENTS[theme])
    image_prompt = f"{subject}, {environment}, {rng.choice(LIGHTING)}, {QUALITY_TAGS}"
    alt_text = f"Cinematic anime-style artwork of a {subject} in a {environment}."

    return {
        "carousel_outline": ["Single Post Focus: standalone cinematic artwork with a short reflection"],
        "caption": caption,
        "cta": cta,
        "hashtags": hashtags,
        "image_prompt": image_prompt,
        "alt_text": alt_text,
    }
