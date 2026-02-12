import test from 'node:test'
import assert from 'node:assert/strict'

import { renderMarkdownToHtml } from '../src/utils/markdownRender.js'

test('renderMarkdownToHtml renders fenced code block', () => {
  const html = renderMarkdownToHtml('```js\nconst x = 1\n```')
  assert.match(html, /<pre><code class="language-js">/)
  assert.match(html, /const x = 1/)
})

test('renderMarkdownToHtml renders inline code and strong text', () => {
  const html = renderMarkdownToHtml('Use `pip install` and **restart**')
  assert.match(html, /<code>pip install<\/code>/)
  assert.match(html, /<strong>restart<\/strong>/)
})
