import re
import unittest

from ai_content_agent.prompts.manager import PACKAGED_PROMPT_DIR, PromptManager

# Variables each agent passes to PromptManager.render (see ai_content_agent/agents/*.py).
AGENT_VARIABLES = {
    "research.md": ["identity", "strategy", "market", "run_date"],
    "planner.md": ["research_json", "market"],
    "creator.md": ["selected_idea", "identity", "constitution", "strategy", "market"],
    "reviewer.md": ["creator_output", "identity", "constitution", "market"],
    "predictor.md": ["creator_output", "research_json", "review_json", "market", "recent_posts_json"],
    "scientist.md": ["experiment_results_json", "identity", "constitution", "strategy"],
}


class PromptTemplateTests(unittest.TestCase):
    def test_every_prompt_file_is_covered(self):
        files = {path.name for path in PACKAGED_PROMPT_DIR.glob("*.md")}
        self.assertEqual(files, set(AGENT_VARIABLES))

    def test_every_variable_reaches_the_rendered_prompt(self):
        manager = PromptManager()
        for name, variables in AGENT_VARIABLES.items():
            with self.subTest(prompt=name):
                rendered = manager.render(name, {v: f"SENTINEL_{v}_END" for v in variables})
                for variable in variables:
                    self.assertIn(f"SENTINEL_{variable}_END", rendered, f"{name} never uses ${variable}")

    def test_prompts_use_no_unknown_placeholders(self):
        for name, variables in AGENT_VARIABLES.items():
            with self.subTest(prompt=name):
                text = (PACKAGED_PROMPT_DIR / name).read_text(encoding="utf-8")
                self.assertLessEqual(set(re.findall(r"\$(\w+)", text)), set(variables))

    def test_default_prompt_dir_is_independent_of_working_directory(self):
        self.assertTrue((PromptManager().prompt_dir / "research.md").exists())


if __name__ == "__main__":
    unittest.main()
