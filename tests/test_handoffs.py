"""Tests for agent handoffs, flag discriminator, MCP client, and stop hooks."""
import json
import unittest
from unittest.mock import MagicMock, patch

from agent.flag_discriminator import FlagDiscriminator, FlagVerdict
from agent.handoffs import HandoffTool
from agent.hooks import HookEngine, HooksConfig, StopHookAction
from tools.mcp_client import MCPBridgeTool, MCPClient, MCPToolSchema


class TestFlagDiscriminator(unittest.TestCase):
    """Tests for the FlagDiscriminator agent."""

    def setUp(self):
        self.disc = FlagDiscriminator()

    def test_valid_flag_standard_format(self):
        v = self.disc.validate("flag{this_is_a_test}")
        self.assertTrue(v.is_valid)
        self.assertEqual(v.confidence, "high")

    def test_valid_flag_ctf_prefix(self):
        v = self.disc.validate("CTF{some_flag_value}")
        self.assertTrue(v.is_valid)

    def test_valid_flag_custom_prefix(self):
        v = self.disc.validate("NCSA{custom_flag_123}")
        self.assertTrue(v.is_valid)

    def test_reject_placeholder(self):
        v = self.disc.validate("flag{...}")
        self.assertFalse(v.is_valid)
        self.assertIn("placeholder", v.reason.lower())

    def test_reject_regex_metacharacters(self):
        v = self.disc.validate("flag{[a-z]+}")
        self.assertFalse(v.is_valid)
        self.assertIn("regex", v.reason.lower())

    def test_reject_too_short_content(self):
        v = self.disc.validate("flag{ab}")
        self.assertFalse(v.is_valid)
        self.assertIn("short", v.reason.lower())

    def test_reject_no_braces(self):
        v = self.disc.validate("not_a_flag_at_all")
        self.assertFalse(v.is_valid)
        self.assertIn("format", v.reason.lower())

    def test_dedup_same_flag(self):
        v1 = self.disc.validate("flag{abc_def}")
        v2 = self.disc.validate("flag{abc_def}")
        self.assertTrue(v1.is_valid)
        self.assertTrue(v2.is_valid)
        self.assertEqual(v2.reason, "Already validated in this session.")

    def test_unknown_prefix_medium_confidence(self):
        v = self.disc.validate("custom{some_value_here}")
        self.assertTrue(v.is_valid)
        self.assertEqual(v.confidence, "medium")

    def test_custom_pattern(self):
        disc = FlagDiscriminator(custom_pattern=r"MYCTF\{[a-zA-Z0-9_]+\}")
        v = disc.validate("MYCTF{test_flag}")
        self.assertTrue(v.is_valid)
        self.assertEqual(v.confidence, "high")

    def test_reject_code_context(self):
        context = "pattern = r'flag{[a-z]+}'"
        v = self.disc.validate("flag{test_value}", context=context)
        # This should still validate the flag itself, not the regex in context
        self.assertTrue(v.is_valid)

    def test_summary_empty(self):
        self.assertEqual(self.disc.summary(), "No flags evaluated.")

    def test_summary_after_validation(self):
        self.disc.validate("flag{test_one}")
        self.disc.validate("flag{...}")
        summary = self.disc.summary()
        self.assertIn("[+]", summary)
        self.assertIn("[x]", summary)

    def test_llm_verify_valid(self):
        """Test LLM verification when provider returns VALID."""
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {
            "message": {"content": "VALID"},
            "usage": None,
        }
        mock_config = MagicMock()
        mock_config.model.fast_model = "gpt-4o-mini"
        disc = FlagDiscriminator(provider=mock_provider, config=mock_config)
        # Use a low-confidence candidate to trigger LLM path
        v = disc.validate("unknown_prefix{some_value}", context="", challenge_description="test")
        # Should be valid (either from heuristic or LLM)
        self.assertTrue(v.is_valid)

    def test_reject_placeholder_variants(self):
        """Test rejection of various placeholder values."""
        for placeholder in ["TODO", "here", "example", "test", "PLACEHOLDER"]:
            v = self.disc.validate(f"flag{{{placeholder}}}")
            self.assertFalse(v.is_valid, f"Should reject placeholder: {placeholder}")


class TestHandoffTool(unittest.TestCase):
    """Tests for the HandoffTool."""

    def test_schema(self):
        tool = HandoffTool()
        schema = tool.openai_schema()
        self.assertEqual(schema["function"]["name"], "agent_handoff")
        params = schema["function"]["parameters"]
        self.assertIn("target", params["properties"])
        self.assertIn("context", params["properties"])

    def test_flag_discriminator_handoff_valid(self):
        tool = HandoffTool()
        result = tool.execute(
            target="flag_discriminator",
            context="flag{real_flag_here}",
            challenge_info="Test challenge",
        )
        self.assertIn("VALIDATED", result)

    def test_flag_discriminator_handoff_invalid(self):
        tool = HandoffTool()
        result = tool.execute(
            target="flag_discriminator",
            context="flag{...}",
            challenge_info="Test challenge",
        )
        self.assertIn("REJECTED", result)

    def test_recon_handoff_no_provider(self):
        tool = HandoffTool()
        result = tool.execute(
            target="recon",
            context="http://example.com",
        )
        self.assertIn("unavailable", result)

    def test_exploit_handoff_no_provider(self):
        tool = HandoffTool()
        result = tool.execute(
            target="exploit",
            context="SQL injection on login form",
        )
        self.assertIn("unavailable", result)

    def test_unknown_target(self):
        tool = HandoffTool()
        result = tool.execute(target="unknown", context="test")
        self.assertIn("Unknown", result)

    def test_recon_handoff_with_provider(self):
        mock_provider = MagicMock()
        mock_provider.chat.return_value = {
            "message": {"content": "nmap -sV target.com\ngobuster dir -u target.com -w wordlist.txt"},
            "usage": None,
        }
        mock_config = MagicMock()
        mock_config.model.fast_model = "gpt-4o-mini"
        tool = HandoffTool(provider=mock_provider, config=mock_config)
        result = tool.execute(target="recon", context="target.com")
        self.assertIn("Recon specialist report", result)


class TestStopHooks(unittest.TestCase):
    """Tests for the stop hook system."""

    def test_no_hooks_always_ok(self):
        engine = HookEngine()
        ok, msg = engine.pre_answer("test answer", "flag{test}")
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_flag_format_check_valid(self):
        cfg = HooksConfig(
            pre_answer=[StopHookAction(check="flag_format", flag_pattern=r"flag\{.+\}")]
        )
        engine = HookEngine(config=cfg)
        ok, msg = engine.pre_answer("my answer", "flag{real_flag}")
        self.assertTrue(ok)

    def test_flag_format_check_invalid(self):
        cfg = HooksConfig(
            pre_answer=[StopHookAction(check="flag_format", flag_pattern=r"flag\{.+\}")]
        )
        engine = HookEngine(config=cfg)
        ok, msg = engine.pre_answer("my answer", "not_a_flag")
        self.assertFalse(ok)
        self.assertIn("does not match", msg)

    def test_flag_format_check_no_flag_with_pattern(self):
        cfg = HooksConfig(
            pre_answer=[StopHookAction(check="flag_format", flag_pattern=r"flag\{.+\}")]
        )
        engine = HookEngine(config=cfg)
        # Using custom_flag_pattern parameter
        ok, msg = engine.pre_answer("my answer", "", custom_flag_pattern=r"flag\{.+\}")
        self.assertFalse(ok)
        self.assertIn("no flag", msg.lower())

    def test_flag_discriminator_check_valid(self):
        cfg = HooksConfig(
            pre_answer=[StopHookAction(check="flag_discriminator")]
        )
        engine = HookEngine(config=cfg)
        ok, msg = engine.pre_answer("answer", "flag{valid_flag_here}")
        self.assertTrue(ok)

    def test_flag_discriminator_check_invalid(self):
        cfg = HooksConfig(
            pre_answer=[StopHookAction(check="flag_discriminator")]
        )
        engine = HookEngine(config=cfg)
        ok, msg = engine.pre_answer("answer", "flag{...}")
        self.assertFalse(ok)
        self.assertIn("rejected", msg.lower())

    def test_shell_check_success(self):
        cfg = HooksConfig(
            pre_answer=[StopHookAction(check="shell", run="true")]
        )
        engine = HookEngine(config=cfg)
        ok, msg = engine.pre_answer("answer", "flag{test}")
        self.assertTrue(ok)

    def test_shell_check_failure(self):
        cfg = HooksConfig(
            pre_answer=[StopHookAction(
                check="shell",
                run="echo 'Bad answer' && exit 1",
                message="Shell check failed",
            )]
        )
        engine = HookEngine(config=cfg)
        ok, msg = engine.pre_answer("answer", "flag{test}")
        self.assertFalse(ok)
        self.assertIn("Bad answer", msg)

    def test_multiple_hooks_first_fails(self):
        cfg = HooksConfig(
            pre_answer=[
                StopHookAction(check="flag_format", flag_pattern=r"flag\{.+\}"),
                StopHookAction(check="flag_discriminator"),
            ]
        )
        engine = HookEngine(config=cfg)
        ok, msg = engine.pre_answer("answer", "bad_flag")
        self.assertFalse(ok)  # First hook rejects


class TestMCPClient(unittest.TestCase):
    """Tests for the MCP client and bridge tool."""

    def test_mcp_tool_schema(self):
        schema = MCPToolSchema(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        )
        self.assertEqual(schema.name, "test_tool")

    def test_mcp_bridge_schema(self):
        bridge = MCPBridgeTool()
        schema = bridge.openai_schema()
        self.assertEqual(schema["function"]["name"], "mcp")
        params = schema["function"]["parameters"]
        self.assertIn("server", params["properties"])
        self.assertIn("tool", params["properties"])

    def test_mcp_bridge_no_server(self):
        bridge = MCPBridgeTool()
        result = bridge.execute(server="nonexistent", tool="test")
        self.assertIn("not connected", result)

    def test_mcp_bridge_available_tools(self):
        bridge = MCPBridgeTool()
        tools = bridge.get_available_tools()
        self.assertEqual(tools, {})

    def test_mcp_client_bad_command(self):
        client = MCPClient("nonexistent_command_12345")
        result = client.connect()
        self.assertFalse(result)


class TestRegistryIntegration(unittest.TestCase):
    """Tests that new tools register correctly."""

    def test_handoff_in_full_registry(self):
        from tools.registry import ToolRegistry
        reg = ToolRegistry()
        self.assertIn("agent_handoff", reg.list_names())

    def test_mcp_in_full_registry(self):
        from tools.registry import ToolRegistry
        reg = ToolRegistry()
        self.assertIn("mcp", reg.list_names())

    def test_handoff_in_subset_registry(self):
        from tools.registry import ToolRegistry
        reg = ToolRegistry.from_subset(["agent_handoff", "answer_user"])
        self.assertIn("agent_handoff", reg.list_names())

    def test_mcp_in_subset_registry(self):
        from tools.registry import ToolRegistry
        reg = ToolRegistry.from_subset(["mcp"])
        self.assertIn("mcp", reg.list_names())


if __name__ == "__main__":
    unittest.main()
