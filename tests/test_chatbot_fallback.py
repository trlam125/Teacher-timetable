import os
import unittest
from unittest.mock import patch
from urllib.error import URLError

from app.chatbot import ChatbotError, _call_gemini_model, _configured_model_chain, _same_model_retryable, ask_gemini


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

    @patch.dict(os.environ, {"GEMINI_MODEL": "gemini-3.7-flash"}, clear=False)
    def test_fallback_chain_keeps_older_stable_model_as_last_resort(self):
        self.assertEqual(
            _configured_model_chain(),
            [
                "gemini-3.7-flash",
                "gemini-3.6-flash",
                "gemini-3.5-flash",
                "gemini-2.5-flash",
            ],
        )

    @patch("app.chatbot.urlopen", side_effect=URLError("temporary network failure"))
    def test_network_error_is_retryable_and_can_fallback(self, _urlopen):
        with self.assertRaises(ChatbotError) as raised:
            _call_gemini_model("gemini-3.7-flash", "test-key", b"{}", timeout_seconds=1)

        self.assertEqual(raised.exception.code, "gemini_network")
        self.assertTrue(raised.exception.retry_with_fallback)
        self.assertTrue(_same_model_retryable(raised.exception))

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
        sleep_backoff.assert_called_once()
        self.assertEqual(sleep_backoff.call_args.args[0], 0)
        self.assertIn("deadline", sleep_backoff.call_args.kwargs)

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
    def test_malformed_pipe_rows_are_made_readable(self, call_model):
        call_model.return_value = (
            "| 7A2, 7A3 | 16 | Cập nhật đủ theo PCCM\n"
            "- Hoàng Thị Nhung | Toán, Tin học | 9A3, 8A3 | 17 | Theo PCCM"
        )

        answer, _, _ = ask_gemini("test", [], self.project_data)

        self.assertNotIn("|", answer)
        self.assertIn("7A2, 7A3 — 16 — Cập nhật đủ theo PCCM", answer)
        self.assertIn("- Hoàng Thị Nhung — Toán, Tin học — 9A3, 8A3 — 17 — Theo PCCM", answer)

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
    def test_valid_markdown_table_is_preserved(self, call_model):
        table = (
            "| Giáo viên | Số tiết |\n"
            "| --- | --- |\n"
            "| Hoàng Thị Nhung | 17 |"
        )
        call_model.return_value = table

        answer, _, _ = ask_gemini("test", [], self.project_data)

        self.assertEqual(answer, table)

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
    def test_prompt_prioritizes_complete_answers_and_has_larger_output_budget(self, call_model):
        import json

        call_model.return_value = "answer"
        ask_gemini("Liệt kê tất cả giáo viên", [], self.project_data)

        payload = json.loads(call_model.call_args.args[2].decode("utf-8"))
        instruction = payload["systemInstruction"]["parts"][0]["text"]
        self.assertIn("không tự rút gọn câu trả lời", instruction.lower())
        self.assertIn("liệt kê đầy đủ tất cả kết quả phù hợp", instruction.lower())
        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 8192)
        self.assertNotIn("temperature", payload["generationConfig"])
        self.assertNotIn("topP", payload["generationConfig"])
        self.assertNotIn("topK", payload["generationConfig"])



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
    def test_max_tokens_is_continued_automatically(self, call_model):
        import json

        call_model.side_effect = [
            ("Phần 1", "MAX_TOKENS"),
            ("Phần 2", "STOP"),
        ]

        answer, model_used, failures = ask_gemini("Liệt kê tất cả", [], self.project_data)

        self.assertEqual(model_used, "primary-model")
        self.assertEqual(failures, [])
        self.assertEqual(answer, "Phần 1\nPhần 2")
        self.assertEqual(call_model.call_count, 2)

        continuation_payload = json.loads(call_model.call_args_list[1].args[2].decode("utf-8"))
        continuation_contents = continuation_payload["contents"]
        self.assertEqual(continuation_contents[-2]["role"], "model")
        self.assertEqual(continuation_contents[-2]["parts"][0]["text"], "Phần 1")
        self.assertEqual(continuation_contents[-1]["role"], "user")
        self.assertIn("Tiếp tục", continuation_contents[-1]["parts"][0]["text"])

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
    def test_max_tokens_mid_word_is_joined_without_breaking_vietnamese(self, call_model):
        call_model.side_effect = [
            ("Lý do: Ph", "MAX_TOKENS"),
            ("ân công theo QĐ 07.", "STOP"),
        ]

        answer, _, _ = ask_gemini("Liệt kê tất cả", [], self.project_data)

        self.assertEqual(answer, "Lý do: Phân công theo QĐ 07.")
        self.assertNotIn("Ph\nân", answer)
        self.assertNotIn("Ph ân", answer)

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
    def test_max_tokens_preserves_leading_space_from_continuation(self, call_model):
        call_model.side_effect = [
            ("Lý do: theo", "MAX_TOKENS"),
            (" phân công theo QĐ 07.", "STOP"),
        ]

        answer, _, _ = ask_gemini("Liệt kê tất cả", [], self.project_data)

        self.assertEqual(answer, "Lý do: theo phân công theo QĐ 07.")

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
    def test_repeated_max_tokens_is_not_silently_treated_as_complete(self, call_model):
        call_model.side_effect = [
            ("Phần 1", "MAX_TOKENS"),
            ("Phần 2", "MAX_TOKENS"),
            ("Phần 3", "MAX_TOKENS"),
        ]

        answer, _, _ = ask_gemini("Liệt kê tất cả", [], self.project_data)

        self.assertEqual(call_model.call_count, 3)
        self.assertIn("Phần 1", answer)
        self.assertIn("Phần 3", answer)
        self.assertIn("đã chạm giới hạn đầu ra", answer)

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
    @patch("app.chatbot.GEMINI_TOTAL_TIMEOUT_SECONDS", 10.0)
    @patch("app.chatbot.GEMINI_REQUEST_TIMEOUT_SECONDS", 60.0)
    @patch("app.chatbot.time.monotonic", side_effect=[100.0, 100.0])
    @patch("app.chatbot._call_gemini_model")
    def test_backend_request_timeout_is_bounded_by_total_deadline(
        self,
        call_model,
        monotonic,
    ):
        call_model.return_value = "answer"

        answer, _, _ = ask_gemini("test", [], self.project_data)

        self.assertEqual(answer, "answer")
        timeout_seconds = call_model.call_args.kwargs["timeout_seconds"]
        self.assertGreater(timeout_seconds, 0)
        self.assertLessEqual(timeout_seconds, 8.0)



    @patch("app.chatbot.urlopen")
    def test_provider_finish_reason_is_read_from_response(self, urlopen_mock):
        import json

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({
                    "candidates": [{
                        "finishReason": "MAX_TOKENS",
                        "content": {"parts": [{"text": "Phần bị cắt"}]},
                    }]
                }).encode("utf-8")

        urlopen_mock.return_value = FakeResponse()

        answer, finish_reason = _call_gemini_model(
            "primary-model",
            "test-key",
            b"{}",
            timeout_seconds=12.5,
        )

        self.assertEqual(answer, "Phần bị cắt")
        self.assertEqual(finish_reason, "MAX_TOKENS")
        self.assertEqual(urlopen_mock.call_args.kwargs["timeout"], 12.5)

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
    @patch("app.chatbot.GEMINI_TOTAL_TIMEOUT_SECONDS", 10.0)
    @patch("app.chatbot.time.monotonic", side_effect=[100.0, 100.0, 109.0])
    @patch("app.chatbot._call_gemini_model")
    def test_total_deadline_stops_retry_chain_before_frontend_timeout(
        self,
        call_model,
        monotonic,
    ):
        call_model.side_effect = ChatbotError(
            "temporary overload",
            code="gemini_http",
            provider_status=503,
            model_name="primary-model",
            retry_with_fallback=True,
        )

        with self.assertRaises(ChatbotError) as raised:
            ask_gemini("test", [], self.project_data)

        self.assertEqual(call_model.call_count, 1)
        self.assertEqual(raised.exception.code, "gemini_deadline")
        self.assertEqual(raised.exception.attempts[-1]["attempt_count"], 1)



if __name__ == "__main__":
    unittest.main()
