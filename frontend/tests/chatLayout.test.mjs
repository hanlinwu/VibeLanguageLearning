import test from 'node:test'
import assert from 'node:assert/strict'

import { getSidebarWidth } from '../src/utils/chatLayout.js'

test('getSidebarWidth returns expanded width by default', () => {
  assert.equal(getSidebarWidth(false), 280)
})

test('getSidebarWidth returns compact width when collapsed', () => {
  assert.equal(getSidebarWidth(true), 60)
})
