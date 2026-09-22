import unittest

from rag_core.ragkit.chatbot import _resolve_abstain
from rag_core.ragkit.messages import chat_message


class ChatMessagesTest(unittest.TestCase):
    def test_action_unavailable_message_is_resource_backed(self):
        self.assertEqual(chat_message("action_unavailable"), "요청하신 데이터를 조회할수 없습니다.")

    def test_failure_messages_are_resource_backed(self):
        self.assertEqual(chat_message("unsupported_commodity"), "지원하지 않는 광물에 대해서는 답변할수 없습니다.")
        self.assertEqual(chat_message("data_not_found"), "데이터를 찾을 수 없습니다.")

    def test_abstain_reason_uses_resource_messages(self):
        self.assertEqual(
            _resolve_abstain("리튬", ["'가상광물'을(를) KOMIS 광종 목록(ai_mnrl_mst)에서 찾지 못했습니다."], None),
            ("unsupported_mineral", chat_message("unsupported_commodity")),
        )
        self.assertEqual(
            _resolve_abstain("리튬", ["조회하신 조건에 해당하는 데이터를 찾지 못했습니다."], None),
            ("no_data_for_period", chat_message("data_not_found")),
        )
