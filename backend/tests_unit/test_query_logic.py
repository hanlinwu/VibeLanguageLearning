import unittest

from app.services.query_logic import cosine_similarity, rank_by_similarity


class QueryLogicTests(unittest.TestCase):
    def test_rank_by_similarity_returns_descending(self) -> None:
        q = [1.0, 0.0]
        candidates = [
            {'id': 1, 'embedding': [0.0, 1.0]},
            {'id': 2, 'embedding': [1.0, 0.0]},
            {'id': 3, 'embedding': [0.7, 0.7]},
        ]
        ranked = rank_by_similarity(q, candidates, top_k=2)
        self.assertEqual([item['id'] for item in ranked], [2, 3])

    def test_cosine_similarity_invalid_vector(self) -> None:
        self.assertEqual(cosine_similarity([], [1.0]), -1.0)


if __name__ == '__main__':
    unittest.main()
