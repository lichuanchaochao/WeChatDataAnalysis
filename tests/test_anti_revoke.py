import unittest
from src.wechat_decrypt_tool.anti_revoke_service import (
    _ensure_weflow_host_executable,
    _is_valid_chat_session,
    get_anti_revoke_config,
    set_anti_revoke_config,
)

class AntiRevokeServiceTest(unittest.TestCase):
    def test_weflow_host_executable(self):
        exe_path = _ensure_weflow_host_executable()
        self.assertTrue(exe_path.endswith("WeFlow.exe"))

    def test_config_get_and_set(self):
        acc = "test_account_anti_revoke_mock"
        initial = get_anti_revoke_config(acc)
        self.assertFalse(initial.get("antiRevokeAutoApplyNewGroups", False))

        set_anti_revoke_config(acc, True)
        updated = get_anti_revoke_config(acc)
        self.assertTrue(updated.get("antiRevokeAutoApplyNewGroups", False))

        set_anti_revoke_config(acc, False)
        reset = get_anti_revoke_config(acc)
        self.assertFalse(reset.get("antiRevokeAutoApplyNewGroups", False))

    def test_session_filter(self):
        self.assertTrue(_is_valid_chat_session("wxid_abc123"))
        self.assertTrue(_is_valid_chat_session("123456789@chatroom"))
        self.assertFalse(_is_valid_chat_session("brandsessionholder"))
        self.assertFalse(_is_valid_chat_session("notifymessage"))
        self.assertFalse(_is_valid_chat_session("gh_12345678"))
        self.assertFalse(_is_valid_chat_session("user@kefu.openim"))
        self.assertFalse(_is_valid_chat_session("@placeholder"))
        self.assertFalse(_is_valid_chat_session("weixin"))

if __name__ == "__main__":
    unittest.main()
