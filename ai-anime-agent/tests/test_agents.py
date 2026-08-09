import unittest

from ai_content_agent.agents.base import BaseAgent
from ai_content_agent.agents.creator import CreatorAgent
from ai_content_agent.agents.planner import PlannerAgent
from ai_content_agent.agents.research import ResearchAgent
from ai_content_agent.agents.reviewer import ReviewerAgent


class AgentFrameworkTests(unittest.TestCase):
    def test_agents_expose_framework_contract(self):
        agents = [
            ResearchAgent(),
            PlannerAgent(),
            CreatorAgent(),
            ReviewerAgent(),
        ]
        for agent in agents:
            self.assertIsInstance(agent, BaseAgent)
            self.assertTrue(agent.name)
            self.assertTrue(agent.description)
            self.assertIsInstance(agent.input_schema, dict)
            self.assertTrue(agent.input_schema)
            self.assertIsInstance(agent.output_schema, dict)
            self.assertTrue(agent.output_schema)
            self.assertTrue(callable(agent.execute))

    def test_research_agent_output_schema_includes_research_id(self):
        self.assertIn("research_id", ResearchAgent().output_schema)

    def test_creator_agent_output_schema_includes_alt_text(self):
        self.assertIn("alt_text", CreatorAgent().output_schema)

    def test_reviewer_agent_output_schema_includes_timestamp(self):
        self.assertIn("timestamp", ReviewerAgent().output_schema)


if __name__ == "__main__":
    unittest.main()
