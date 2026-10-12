import sys
import unittest
sys.path.insert(0, 'src')

class TestBackportedFeatures(unittest.TestCase):
    def test_anti_revoke_preserved(self):
        loader = unittest.TestLoader()
        suite = loader.discover('tests', pattern='test_anti_revoke.py')
        runner = unittest.TextTestRunner(verbosity=0)
        res = runner.run(suite)
        self.assertTrue(res.wasSuccessful())

    def test_pinyin_search(self):
        from wechat_decrypt_tool.routers.chat_contacts import _build_contact_pinyin_search_forms, _matches_pinyin_keyword
        forms = _build_contact_pinyin_search_forms('张伟')
        # forms is a tuple of (initials, full, spans) candidates
        self.assertEqual(forms[0][0], 'zw')
        self.assertEqual(forms[0][1], 'zhangwei')
        self.assertTrue(_matches_pinyin_keyword('张伟', 'zw'))
        self.assertTrue(_matches_pinyin_keyword('单田芳', 'shan'))

    def test_image_xor_decode(self):
        from wechat_decrypt_tool.media_helpers import _xor_bytes
        raw = bytes([0xFF ^ 0x5A, 0xD8 ^ 0x5A, 0xFF ^ 0x5A, 0xE0 ^ 0x5A])
        dec = _xor_bytes(raw, 0x5A)
        self.assertEqual(dec[:3], b'\xFF\xD8\xFF')

    def test_ai_store_and_lifecycle(self):
        from wechat_decrypt_tool.ai.service import get_ai_service
        s = get_ai_service()
        self.assertIsNotNone(s.account_lifecycle_lock)

    def test_voice_transcription_mirror(self):
        from wechat_decrypt_tool import runtime_settings, voice_transcription
        self.assertIn(runtime_settings.read_voice_model_download_source(), ('huggingface', 'hf-mirror'))
        ep = voice_transcription._voice_model_download_endpoint('hf-mirror', 'pkufool/zipformer-small')
        self.assertTrue(ep.startswith('http'))

    def test_remote_vector_model(self):
        from wechat_decrypt_tool.local_search import catalog, inference, index
        spec = catalog.remote_spec('remote-openai', 'http://127.0.0.1:11434', 'bge-m3')
        self.assertEqual(spec['backend'], 'remote')
        self.assertTrue(inference.is_lan_endpoint('http://192.168.1.1:11434'))
        chunks = index.make_chunks([{'text': 'abc', 'username': 'u1', 'time': 1, 'source': 's1'}], tokenizer=None, max_chars=50)
        self.assertEqual(len(chunks), 1)

    def test_chat_export_location(self):
        from wechat_decrypt_tool.chat_export_service import _parse_location_message
        loc = _parse_location_message('<msg><location x="39.9" y="116.4" scale="16" label="Beijing" poiname="Sanlitun"/></msg>')
        self.assertEqual(loc.get('renderType'), 'location')
        self.assertEqual(loc.get('locationPoiname'), 'Sanlitun')

if __name__ == '__main__':
    unittest.main()
