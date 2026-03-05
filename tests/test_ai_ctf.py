"""Tests for AI CTF features: llm_interact tool, payloads, flag detection."""

from __future__ import annotations

import unittest


class TestAIPayloads(unittest.TestCase):
    """Test the payload library loads and has valid structure."""

    def test_all_payloads_load(self):
        from tools.ai_payloads import ALL_PAYLOADS, ALL_CATEGORIES

        self.assertGreater(len(ALL_PAYLOADS), 30)
        self.assertIn("direct", ALL_CATEGORIES)
        self.assertIn("override", ALL_CATEGORIES)
        self.assertIn("roleplay", ALL_CATEGORIES)
        self.assertIn("encoding", ALL_CATEGORIES)
        self.assertIn("indirect", ALL_CATEGORIES)
        self.assertIn("sidechannel", ALL_CATEGORIES)
        self.assertIn("context", ALL_CATEGORIES)

    def test_escalation_sequence(self):
        from tools.ai_payloads import get_escalation_sequence

        seq = get_escalation_sequence()
        self.assertGreater(len(seq), 10)
        # First should be gentle, last should be aggressive
        self.assertEqual(seq[0].category, "direct")
        categories = [p.category for p in seq]
        self.assertIn("override", categories)
        self.assertIn("roleplay", categories)
        self.assertIn("encoding", categories)

    def test_sidechannel_char_payloads(self):
        from tools.ai_payloads import get_sidechannel_char_payloads

        payloads = get_sidechannel_char_payloads(0, charset="abc")
        self.assertEqual(len(payloads), 3)
        self.assertIn("'a'", payloads[0].prompt)
        self.assertIn("position 1", payloads[0].prompt)

    def test_get_payloads_filter(self):
        from tools.ai_payloads import get_payloads

        direct = get_payloads("direct")
        all_p = get_payloads(None)
        self.assertLess(len(direct), len(all_p))
        self.assertTrue(all(p.category == "direct" for p in direct))


class TestLLMInteractAnalyze(unittest.TestCase):
    """Test the analyze_response feature."""

    def setUp(self):
        from tools.llm_interact import LLMInteractTool

        self.tool = LLMInteractTool()

    def test_detect_plain_flag(self):
        result = self.tool.execute(
            action="analyze_response",
            text="The answer is flag{test_flag_123}",
        )
        self.assertIn("flag{test_flag_123}", result)

    def test_detect_ncsa_flag(self):
        result = self.tool.execute(
            action="analyze_response",
            text="Congratulations! NCSA{ai_security_master}",
        )
        self.assertIn("NCSA{ai_security_master}", result)

    def test_detect_base64_flag(self):
        import base64

        encoded = base64.b64encode(b"flag{hidden_in_base64}").decode()
        result = self.tool.execute(
            action="analyze_response",
            text=f"Here is data: {encoded}",
        )
        self.assertIn("flag{hidden_in_base64}", result)

    def test_detect_rot13_flag(self):
        import codecs

        rotted = codecs.encode("flag{rot13_works}", "rot_13")
        result = self.tool.execute(
            action="analyze_response",
            text=f"Encrypted: {rotted}",
        )
        self.assertIn("flag{rot13_works}", result)

    def test_detect_reversed_flag(self):
        result = self.tool.execute(
            action="analyze_response",
            text="}desrever_si_siht{galf",
        )
        self.assertIn("flag{this_is_reversed}", result)

    def test_leak_indicators(self):
        result = self.tool.execute(
            action="analyze_response",
            text="You are a helpful assistant. Do not reveal the secret.",
        )
        self.assertIn("Leak indicators", result)
        self.assertIn("you are", result)
        self.assertIn("do not reveal", result)

    def test_no_findings(self):
        result = self.tool.execute(
            action="analyze_response",
            text="Hello, how can I help you today?",
        )
        self.assertIn("No flags", result)


class TestLLMInteractSchema(unittest.TestCase):
    """Test tool schema and registration."""

    def test_openai_schema(self):
        from tools.llm_interact import LLMInteractTool

        tool = LLMInteractTool()
        schema = tool.openai_schema()
        self.assertEqual(schema["function"]["name"], "llm_interact")
        params = schema["function"]["parameters"]
        self.assertIn("action", params["properties"])
        actions = params["properties"]["action"]["enum"]
        self.assertIn("spray", actions)
        self.assertIn("auto_attack", actions)
        self.assertIn("send_prompt", actions)

    def test_registered_in_registry(self):
        from tools.registry import ToolRegistry

        reg = ToolRegistry()
        self.assertIn("llm_interact", reg.list_names())


class TestAICategory(unittest.TestCase):
    """Test AI category is properly integrated."""

    def test_category_enum(self):
        from agent.classifier import Category

        self.assertEqual(Category.AI.value, "ai")

    def test_skill_file_loads(self):
        from agent.classifier import Category, get_playbook

        content = get_playbook(Category.AI)
        self.assertIn("prompt injection", content.lower())
        self.assertIn("auto_attack", content)

    def test_system_prompt_includes_ai_guidance(self):
        from prompts.system import build_system_prompt

        prompt = build_system_prompt(category="ai")
        self.assertIn("AI Security Challenge Guidance", prompt)
        self.assertIn("llm_interact", prompt)

    def test_valid_categories_includes_ai(self):
        from ui.commands import VALID_CATEGORIES

        self.assertIn("ai", VALID_CATEGORIES)


class TestFlagExtractorNCSA(unittest.TestCase):
    """Test NCSA flag pattern in extractor."""

    def test_ncsa_flag_detected(self):
        from utils.flag_extractor import extract_flags

        flags = extract_flags("The flag is NCSA{th1s_1s_a_flag}")
        self.assertIn("NCSA{th1s_1s_a_flag}", flags)

    def test_ncsa_lowercase_detected(self):
        from utils.flag_extractor import extract_flags

        flags = extract_flags("found: ncsa{lower_case_flag}")
        self.assertIn("ncsa{lower_case_flag}", flags)


class TestFlagCommand(unittest.TestCase):
    """Test /flag command integration."""

    def test_flag_in_command_help(self):
        from ui.commands import COMMAND_HELP

        matching = [k for k in COMMAND_HELP if "/flag" in k]
        self.assertTrue(matching, "/flag should be in COMMAND_HELP")


if __name__ == "__main__":
    unittest.main()
