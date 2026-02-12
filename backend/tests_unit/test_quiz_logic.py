import unittest

from app.services.quiz_logic import build_questions, grade_answers


class QuizLogicTests(unittest.TestCase):
    def test_build_questions_contains_mcq_and_fill_blank(self) -> None:
        questions = build_questions(['etre', 'avoir'], weak_point='conjugation', num_questions=4)
        kinds = {q['type'] for q in questions}
        self.assertIn('mcq', kinds)
        self.assertIn('fill_blank', kinds)
        self.assertEqual(len(questions), 4)

    def test_grade_answers_is_case_insensitive(self) -> None:
        expected = ['A', 'b', 'C']
        answers = ['a', 'B', 'x']
        correct, total, score = grade_answers(expected, answers)
        self.assertEqual((correct, total), (2, 3))
        self.assertAlmostEqual(score, 2/3)


if __name__ == '__main__':
    unittest.main()
