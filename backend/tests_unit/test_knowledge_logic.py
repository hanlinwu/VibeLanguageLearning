import unittest
from unittest.mock import patch

from app.services.knowledge_logic import decode_text_content, extract_text_payload, split_chunks_stable


class KnowledgeLogicTests(unittest.TestCase):
    def test_decode_text_content_handles_non_utf8(self) -> None:
        raw = b"l\xe2ve"
        text = decode_text_content(raw)
        self.assertTrue(len(text) > 0)

    def test_extract_text_payload_from_json_dict_values(self) -> None:
        raw = b'{"a":"bonjour","b":"salut"}'
        text = extract_text_payload(raw, 'application/json')
        self.assertIn('bonjour', text)
        self.assertIn('salut', text)

    def test_extract_text_payload_routes_pdf_by_content_type(self) -> None:
        with patch('app.services.knowledge_logic.extract_pdf_payload', return_value='pdf text') as mock_pdf:
            text = extract_text_payload(b'%PDF-1.4...', 'application/pdf')
            self.assertEqual(text, 'pdf text')
            mock_pdf.assert_called_once()

    def test_extract_text_payload_routes_docx_by_extension(self) -> None:
        with patch('app.services.knowledge_logic.extract_docx_payload', return_value='docx text') as mock_docx:
            text = extract_text_payload(b'PK...', 'application/octet-stream', filename='notes.docx')
            self.assertEqual(text, 'docx text')
            mock_docx.assert_called_once()

    def test_split_chunks_stable_respects_max_chars(self) -> None:
        text = '\n'.join(['a'] * 30)
        chunks = split_chunks_stable(text, max_chars=10)
        self.assertTrue(len(chunks) > 1)
        self.assertTrue(all(len(chunk) <= 10 for chunk in chunks))


if __name__ == '__main__':
    unittest.main()
