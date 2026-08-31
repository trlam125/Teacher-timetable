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
            "GEMINI_ATTEMPTS_PER_MODEL": "1",
            "GEMINI_RETRY_BASE_SECONDS": "0",
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
        self.assertEqual(model_used, "gemini-3.6-flash")
        self.assertEqual([item.args[0] for item in call_model.call_args_list], ["primary-model", "gemini-3.6-flash"])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["model"], "primary-model")
        self.assertEqual(failures[0]["provider_status"], 429)

    @patch.dict(
        os.environ,
        {
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MODEL": "primary-model",
            "GEMINI_ATTEMPTS_PER_MODEL": "1",
            "GEMINI_RETRY_BASE_SECONDS": "0",
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
        self.assertEqual(model_used, "gemini-3.5-flash")
        self.assertEqual(
            [item.args[0] for item in call_model.call_args_list],
            ["primary-model", "gemini-3.6-flash", "gemini-3.5-flash"],
        )
        self.assertEqual([item["model"] for item in failures], ["primary-model", "gemini-3.6-flash"])


    @patch.dict(
        os.environ,
        {
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MODEL": "primary-model",
            "GEMINI_ATTEMPTS_PER_MODEL": "1",
            "GEMINI_RETRY_BASE_SECONDS": "0",
        },
        clear=False,
    )
    @patch("app.chatbot._call_gemini_model")
    def test_preferred_fallback_never_skips_primary(self, call_model):
        call_model.return_value = "primary answer"

        answer, model_used, failures = ask_gemini(
            "test",
            [],
            self.project_data,
            preferred_model="gemini-3.6-flash",
        )

        self.assertEqual(answer, "primary answer")
        self.assertEqual(model_used, "primary-model")
        self.assertEqual(failures, [])
        self.assertEqual([item.args[0] for item in call_model.call_args_list], ["primary-model"])

    @patch.dict(
        os.environ,
        {
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MODEL": "primary-model",
            "GEMINI_ATTEMPTS_PER_MODEL": "2",
            "GEMINI_RETRY_BASE_SECONDS": "0",
        },
        clear=False,
    )
    @patch("app.chatbot._sleep_with_backoff")
    @patch("app.chatbot._call_gemini_model")
    def test_transient_503_retries_same_model_before_fallback(self, call_model, sleep_backoff):
        call_model.side_effect = [
            ChatbotError(
                "temporary overload",
                code="gemini_http",
                provider_status=503,
                model_name="primary-model",
                retry_with_fallback=True,
            ),
            "primary recovered",
        ]

        answer, model_used, failures = ask_gemini("test", [], self.project_data)

        self.assertEqual(answer, "primary recovered")
        self.assertEqual(model_used, "primary-model")
        self.assertEqual(failures, [])
        self.assertEqual(
            [item.args[0] for item in call_model.call_args_list],
            ["primary-model", "primary-model"],
        )
        sleep_backoff.assert_called_once_with(0)

    @patch.dict(
        os.environ,
        {
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MODEL": "primary-model",
            "GEMINI_ATTEMPTS_PER_MODEL": "1",
            "GEMINI_RETRY_BASE_SECONDS": "0",
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
