import unittest

from app.db import build_pgvector_bootstrap_sql


class PgvectorSetupTests(unittest.TestCase):
    def test_bootstrap_sql_contains_extension_and_index(self) -> None:
        statements = build_pgvector_bootstrap_sql(lists=120)
        merged = '\n'.join(statements).lower()
        self.assertIn('create extension if not exists vector', merged)
        self.assertIn('create index if not exists idx_knowledge_chunks_embedding_ivfflat', merged)
        self.assertIn('vector_cosine_ops', merged)
        self.assertIn('lists = 120', merged)


if __name__ == '__main__':
    unittest.main()
