import os
import unittest
from unittest.mock import patch

from app.chatbot import ChatbotError, ask_gemini


class ChatbotFallbackTests(unittest.TestCase):
    def setUp(self):
        self.project_data = {
            "project": {"name": "Test"},
            "teachers": [],
            "subjects": [],
            "classes": [],
            "assignments": [],
            "lessons": [],
        }

    @patch.dict(
        os.environ,
        {
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MODEL": "primary-model",
            "GEMINI_FALLBACK_MODELS": "fallback-1,fallback-2",
        },
        clear=False,
    )
    @patch("app.chatbot._call_gemini_model")
    def test_retryable_primary_error_uses_next_fallback(self, call_model):
        call_model.side_effect = [
            ChatbotError(
                "primary unavailable",
                code="gemini_rate_limit",
                provider_status=429,
                model_name="primary-model",
                retry_with_fallback=True,
            ),
            "fallback answer",
        ]

        answer, model_used, failures = ask_gemini(
            "test",
            [],
            self.project_data,
        )

        self.assertEqual(answer, "fallback answer")
        self.assertEqual(model_used, "fallback-1")
        self.assertEqual([item.args[0] for item in call_model.call_args_list], ["primary-model", "fallback-1"])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["model"], "primary-model")
        self.assertEqual(failures[0]["provider_status"], 429)

    @patch.dict(
        os.environ,
        {
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MODEL": "primary-model",
            "GEMINI_FALLBACK_MODELS": "fallback-1,fallback-2",
        },
        clear=False,
    )
    @patch("app.chatbot._call_gemini_model")
    def test_multiple_retryable_errors_reach_last_fallback(self, call_model):
        call_model.side_effect = [
            ChatbotError("primary failed", code="gemini_http", provider_status=503, retry_with_fallback=True),
            ChatbotError("fallback 1 failed", code="gemini_empty_response", retry_with_fallback=True),
            "last fallback answer",
        ]

        answer, model_used, failures = ask_gemini("test", [], self.project_data)

        self.assertEqual(answer, "last fallback answer")
        self.assertEqual(model_used, "fallback-2")
        self.assertEqual(
            [item.args[0] for item in call_model.call_args_list],
            ["primary-model", "fallback-1", "fallback-2"],
        )
        self.assertEqual([item["model"] for item in failures], ["primary-model", "fallback-1"])

    @patch.dict(
        os.environ,
        {
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MODEL": "primary-model",
            "GEMINI_FALLBACK_MODELS": "fallback-1,fallback-2",
        },
        clear=False,
    )
    @patch("app.chatbot._call_gemini_model")
    def test_non_retryable_error_does_not_fallback(self, call_model):
        call_model.side_effect = ChatbotError(
            "bad api key",
            code="gemini_auth",
            provider_status=403,
            retry_with_fallback=False,
        )

        with self.assertRaises(ChatbotError) as raised:
            ask_gemini("test", [], self.project_data)

        self.assertEqual(call_model.call_count, 1)
        self.assertEqual(raised.exception.attempts[0]["model"], "primary-model")


if __name__ == "__main__":
    unittest.main()
