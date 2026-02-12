import unittest

from app.services.knowledge_logic import extract_text_payload, split_chunks_stable


class KnowledgeLogicTests(unittest.TestCase):
    def test_extract_text_payload_from_json_dict_values(self) -> None:
        raw = b'{"a":"bonjour","b":"salut"}'
        text = extract_text_payload(raw, 'application/json')
        self.assertIn('bonjour', text)
        self.assertIn('salut', text)

    def test_split_chunks_stable_respects_max_chars(self) -> None:
        text = '\n'.join(['a'] * 30)
        chunks = split_chunks_stable(text, max_chars=10)
        self.assertTrue(len(chunks) > 1)
        self.assertTrue(all(len(chunk) <= 10 for chunk in chunks))


if __name__ == '__main__':
    unittest.main()
