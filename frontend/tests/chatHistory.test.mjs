import test from 'node:test'
import assert from 'node:assert/strict'

import { findConversationIndex, orderConversation } from '../src/utils/chatHistory.js'

test('orderConversation sorts turns by created_at ascending', () => {
  const turns = [
    { id: 3, created_at: '2026-02-12T10:02:00.000Z' },
    { id: 1, created_at: '2026-02-12T10:00:00.000Z' },
    { id: 2, created_at: '2026-02-12T10:01:00.000Z' },
  ]

  const ordered = orderConversation(turns)
  assert.deepEqual(
    ordered.map((item) => item.id),
    [1, 2, 3],
  )
})

test('findConversationIndex returns turn index by id', () => {
  const orderedTurns = [
    { id: 1, created_at: '2026-02-12T10:00:00.000Z' },
    { id: 2, created_at: '2026-02-12T10:01:00.000Z' },
    { id: 3, created_at: '2026-02-12T10:02:00.000Z' },
  ]

  assert.equal(findConversationIndex(orderedTurns, 2), 1)
  assert.equal(findConversationIndex(orderedTurns, 99), -1)
})
