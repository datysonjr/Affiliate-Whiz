"""Unit tests for LLMTool and CMSTool."""

import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from src.agents.tools.llm_tool import LLMTool
from src.agents.tools.cms_tool import CMSTool


# ---------------------------------------------------------------------------
# LLMTool tests
# ---------------------------------------------------------------------------


class TestLLMToolInit:
    def test_default_config(self):
        tool = LLMTool({"primary_api_key": "test-key"})
        assert tool.primary_provider == "anthropic"
        assert tool.primary_api_key == "test-key"
        assert tool.fallback_provider is None

    def test_custom_config(self):
        tool = LLMTool({
            "primary_provider": "openai",
            "primary_model": "gpt-4o",
            "primary_api_key": "pk",
            "fallback_provider": "anthropic",
            "fallback_model": "claude-sonnet-4-20250514",
            "fallback_api_key": "fk",
            "default_max_tokens": 2048,
            "temperature": 0.5,
        })
        assert tool.primary_provider == "openai"
        assert tool.fallback_provider == "anthropic"
        assert tool.default_max_tokens == 2048
        assert tool.temperature == 0.5

    def test_unsupported_provider_raises(self):
        tool = LLMTool({
            "primary_provider": "llama-local",
            "primary_api_key": "x",
        })
        with pytest.raises(ValueError, match="Unsupported provider"):
            tool._init_client("llama-local", "model", "key")


class TestLLMToolGenerate:
    def _make_tool_with_mock(self, response_content="Generated text"):
        """Create an LLMTool with a mocked _call_provider."""
        tool = LLMTool({
            "primary_provider": "anthropic",
            "primary_api_key": "test-key",
        })
        tool._call_provider = MagicMock(return_value={
            "content": response_content,
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "provider": "anthropic",
            "model": "claude-sonnet-4-20250514",
        })
        return tool

    def test_generate_success(self):
        tool = self._make_tool_with_mock("Hello world")
        result = tool.generate("Say hello")
        assert result == "Hello world"
        assert tool._total_prompt_tokens == 10
        assert tool._total_completion_tokens == 20

    def test_generate_empty_prompt_raises(self):
        tool = self._make_tool_with_mock()
        with pytest.raises(ValueError, match="Prompt must not be empty"):
            tool.generate("")

    def test_generate_messages(self):
        tool = self._make_tool_with_mock("Response")
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        result = tool.generate_messages(msgs)
        assert result == "Response"

    def test_generate_messages_empty_raises(self):
        tool = self._make_tool_with_mock()
        with pytest.raises(ValueError, match="Messages list must not be empty"):
            tool.generate_messages([])

    def test_summarize(self):
        tool = self._make_tool_with_mock("Short summary")
        result = tool.summarize("This is a long text that needs summarizing.")
        assert result == "Short summary"

    def test_classify(self):
        tool = self._make_tool_with_mock("positive")
        result = tool.classify("Great product!", ["positive", "negative", "neutral"])
        assert result == "positive"

    def test_extract(self):
        tool = self._make_tool_with_mock('{"name": "Widget", "price": 9.99}')
        result = tool.extract(
            "The Widget costs $9.99",
            {"name": "string", "price": "float"},
        )
        assert result["name"] == "Widget"
        assert result["price"] == 9.99

    def test_extract_bad_json_returns_none_values(self):
        tool = self._make_tool_with_mock("not valid json")
        result = tool.extract("some text", {"field1": "string", "field2": "int"})
        assert result == {"field1": None, "field2": None}


class TestLLMToolFallback:
    def test_fallback_on_primary_failure(self):
        tool = LLMTool({
            "primary_provider": "anthropic",
            "primary_api_key": "bad-key",
            "fallback_provider": "openai",
            "fallback_model": "gpt-4o",
            "fallback_api_key": "fallback-key",
            "retry_attempts": 1,
            "retry_delay": 0.0,
        })

        # Mock _dispatch_call to fail on anthropic, succeed on openai
        call_count = {"primary": 0, "fallback": 0}

        def mock_dispatch(provider, client, model, messages, max_tokens, temp):
            if provider == "anthropic":
                call_count["primary"] += 1
                raise RuntimeError("Primary down")
            call_count["fallback"] += 1
            return {
                "content": "Fallback response",
                "prompt_tokens": 5,
                "completion_tokens": 10,
                "provider": "openai",
                "model": "gpt-4o",
            }

        tool._dispatch_call = mock_dispatch
        # Mock client init to return a dummy
        tool._init_client = MagicMock(return_value="mock-client")

        result = tool.generate("Test prompt")
        assert result == "Fallback response"
        assert call_count["primary"] == 1
        assert call_count["fallback"] == 1
        assert tool._fallback_requests == 1

    def test_all_providers_fail_raises(self):
        tool = LLMTool({
            "primary_provider": "anthropic",
            "primary_api_key": "bad",
            "fallback_provider": "openai",
            "fallback_api_key": "also-bad",
            "retry_attempts": 1,
            "retry_delay": 0.0,
        })

        def mock_dispatch(provider, client, model, messages, max_tokens, temp):
            raise RuntimeError(f"{provider} is down")

        tool._dispatch_call = mock_dispatch
        tool._init_client = MagicMock(return_value="mock-client")

        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            tool.generate("Test")


class TestLLMToolUsageStats:
    def test_usage_tracking(self):
        tool = LLMTool({"primary_api_key": "test"})
        tool._track_usage(100, 50)
        tool._track_usage(200, 100)
        stats = tool.get_usage_stats()
        assert stats["total_prompt_tokens"] == 300
        assert stats["total_completion_tokens"] == 150
        assert stats["total_tokens"] == 450

    def test_reset_usage(self):
        tool = LLMTool({"primary_api_key": "test"})
        tool._track_usage(100, 50)
        tool.reset_usage_stats()
        stats = tool.get_usage_stats()
        assert stats["total_tokens"] == 0


# ---------------------------------------------------------------------------
# CMSTool tests
# ---------------------------------------------------------------------------


class TestCMSToolInit:
    def test_default_config(self):
        tool = CMSTool({"api_base_url": "https://example.com/wp-json/wp/v2"})
        assert tool.cms_type == "wordpress"
        assert tool.default_status == "draft"
        assert tool.api_base_url == "https://example.com/wp-json/wp/v2"

    def test_build_url(self):
        tool = CMSTool({"api_base_url": "https://example.com/wp-json/wp/v2/"})
        assert tool._build_url("/posts") == "https://example.com/wp-json/wp/v2/posts"
        assert tool._build_url("media") == "https://example.com/wp-json/wp/v2/media"


class TestCMSToolSession:
    def test_wordpress_basic_auth(self):
        tool = CMSTool({
            "cms_type": "wordpress",
            "api_base_url": "https://example.com/wp-json/wp/v2",
            "username": "admin",
            "api_key": "app-password",
        })
        session = tool._get_session()
        assert session.auth == ("admin", "app-password")
        assert session.headers["User-Agent"] == "OpenClaw/0.1.0"

    def test_bearer_auth(self):
        tool = CMSTool({
            "cms_type": "ghost",
            "api_base_url": "https://example.com/api",
            "api_key": "some-token",
        })
        session = tool._get_session()
        assert session.headers["Authorization"] == "Bearer some-token"


class TestCMSToolCreatePost:
    def test_create_post_missing_title_raises(self):
        tool = CMSTool({"api_base_url": "https://example.com/wp-json/wp/v2"})
        with pytest.raises(ValueError, match="Post title is required"):
            tool.create_post({"content": "body"})

    def test_create_post_missing_content_raises(self):
        tool = CMSTool({"api_base_url": "https://example.com/wp-json/wp/v2"})
        with pytest.raises(ValueError, match="Post content is required"):
            tool.create_post({"title": "Test"})

    @patch("src.agents.tools.cms_tool.CMSTool._request")
    def test_create_post_success(self, mock_request):
        mock_request.return_value = {
            "id": 42,
            "title": {"rendered": "Test Post"},
            "link": "https://example.com/test-post/",
            "slug": "test-post",
            "status": "draft",
            "date": "2025-01-01T00:00:00",
            "modified": "2025-01-01T00:00:00",
        }

        tool = CMSTool({
            "api_base_url": "https://example.com/wp-json/wp/v2",
            "api_key": "test",
            "username": "admin",
        })
        result = tool.create_post({
            "title": "Test Post",
            "content": "<p>Hello</p>",
        })

        assert result["id"] == 42
        assert result["url"] == "https://example.com/test-post/"
        assert result["status"] == "draft"
        mock_request.assert_called_once()

    @patch("src.agents.tools.cms_tool.CMSTool._request")
    def test_create_post_applies_defaults(self, mock_request):
        mock_request.return_value = {
            "id": 1,
            "title": {"rendered": "T"},
            "link": "https://example.com/t/",
            "slug": "t",
            "status": "draft",
            "date": "",
            "modified": "",
        }

        tool = CMSTool({
            "api_base_url": "https://example.com/wp-json/wp/v2",
            "default_status": "private",
            "default_author_id": 5,
        })
        tool.create_post({"title": "T", "content": "C"})

        call_args = mock_request.call_args
        data = call_args.kwargs.get("json_data") or call_args[1].get("json_data")
        assert data["status"] == "private"
        assert data["author"] == 5


class TestCMSToolUpdatePost:
    def test_invalid_post_id_raises(self):
        tool = CMSTool({"api_base_url": "https://example.com/wp-json/wp/v2"})
        with pytest.raises(ValueError, match="Invalid post_id"):
            tool.update_post(-1, {"title": "New"})

    @patch("src.agents.tools.cms_tool.CMSTool._request")
    def test_update_post_success(self, mock_request):
        mock_request.return_value = {
            "id": 42,
            "title": {"rendered": "Updated"},
            "link": "https://example.com/updated/",
            "slug": "updated",
            "status": "publish",
            "date": "",
            "modified": "",
        }

        tool = CMSTool({"api_base_url": "https://example.com/wp-json/wp/v2"})
        result = tool.update_post(42, {"title": "Updated"})
        assert result["title"] == "Updated"


class TestCMSToolDeletePost:
    def test_invalid_post_id_raises(self):
        tool = CMSTool({"api_base_url": "https://example.com/wp-json/wp/v2"})
        with pytest.raises(ValueError, match="Invalid post_id"):
            tool.delete_post(0)

    @patch("src.agents.tools.cms_tool.CMSTool._request")
    def test_delete_post_success(self, mock_request):
        mock_request.return_value = {}
        tool = CMSTool({"api_base_url": "https://example.com/wp-json/wp/v2"})
        assert tool.delete_post(42) is True


class TestCMSToolGetPosts:
    @patch("src.agents.tools.cms_tool.CMSTool._request")
    def test_get_posts_returns_list(self, mock_request):
        mock_request.return_value = [
            {
                "id": 1,
                "title": {"rendered": "Post 1"},
                "link": "https://example.com/post-1/",
                "slug": "post-1",
                "status": "publish",
                "date": "",
                "modified": "",
            },
        ]

        tool = CMSTool({"api_base_url": "https://example.com/wp-json/wp/v2"})
        posts = tool.get_posts({"status": "publish"})
        assert len(posts) == 1
        assert posts[0]["title"] == "Post 1"


class TestCMSToolEnsureCategoryTag:
    @patch("src.agents.tools.cms_tool.CMSTool._request")
    def test_ensure_category_existing(self, mock_request):
        mock_request.return_value = [
            {"id": 7, "name": "Reviews", "slug": "reviews"},
        ]
        tool = CMSTool({"api_base_url": "https://example.com/wp-json/wp/v2"})
        cat_id = tool.ensure_category("Reviews")
        assert cat_id == 7

    @patch("src.agents.tools.cms_tool.CMSTool._request")
    def test_ensure_category_creates_new(self, mock_request):
        # First call: search returns empty; second call: create returns new
        mock_request.side_effect = [
            [],
            {"id": 15, "name": "NewCat"},
        ]
        tool = CMSTool({"api_base_url": "https://example.com/wp-json/wp/v2"})
        cat_id = tool.ensure_category("NewCat")
        assert cat_id == 15

    @patch("src.agents.tools.cms_tool.CMSTool._request")
    def test_ensure_tag_existing(self, mock_request):
        mock_request.return_value = [
            {"id": 3, "name": "vpn", "slug": "vpn"},
        ]
        tool = CMSTool({"api_base_url": "https://example.com/wp-json/wp/v2"})
        tag_id = tool.ensure_tag("vpn")
        assert tag_id == 3


class TestCMSToolHandleResponse:
    def test_401_raises(self):
        tool = CMSTool({"api_base_url": "https://example.com/wp-json/wp/v2"})
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        with pytest.raises(RuntimeError, match="authentication failed"):
            tool._handle_response(mock_resp)

    def test_403_raises(self):
        tool = CMSTool({"api_base_url": "https://example.com/wp-json/wp/v2"})
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"
        with pytest.raises(RuntimeError, match="permission denied"):
            tool._handle_response(mock_resp)

    def test_204_returns_empty_dict(self):
        tool = CMSTool({"api_base_url": "https://example.com/wp-json/wp/v2"})
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.raise_for_status = MagicMock()
        result = tool._handle_response(mock_resp)
        assert result == {}
