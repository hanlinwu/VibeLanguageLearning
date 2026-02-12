import test from 'node:test'
import assert from 'node:assert/strict'

import { summarizeProgress } from '../src/utils/learningProgress.js'

test('summarizeProgress returns mastered and weak counts', () => {
  const result = summarizeProgress({
    mastery: { etre: 0.8, avoir: 0.35, article: 0.55 },
    weak_points: ['avoir'],
  })

  assert.equal(result.masteredCount, 1)
  assert.equal(result.learningCount, 1)
  assert.equal(result.weakCount, 1)
  assert.equal(result.totalTopics, 3)
})
