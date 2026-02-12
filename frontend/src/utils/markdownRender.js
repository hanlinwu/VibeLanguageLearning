function escapeHtml(input) {
  return input
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function renderInline(text) {
  return text
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
}

export function renderMarkdownToHtml(markdown) {
  if (!markdown || !markdown.trim()) {
    return '<p>...</p>'
  }

  const escaped = escapeHtml(markdown)
  const codeFencePattern = /```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g
  let html = ''
  let lastIndex = 0
  let match

  while ((match = codeFencePattern.exec(escaped)) !== null) {
    const blockBefore = escaped.slice(lastIndex, match.index)
    if (blockBefore.trim()) {
      html += blockBefore
        .split(/\n{2,}/)
        .map((paragraph) => `<p>${renderInline(paragraph).replaceAll('\n', '<br/>')}</p>`)
        .join('')
    }

    const lang = match[1] || 'plain'
    const code = match[2].replace(/\n$/, '')
    html += `<pre><code class="language-${lang}">${code}</code></pre>`
    lastIndex = codeFencePattern.lastIndex
  }

  const tail = escaped.slice(lastIndex)
  if (tail.trim()) {
    html += tail
      .split(/\n{2,}/)
      .map((paragraph) => {
        const line = paragraph.trim()
        if (line.startsWith('# ')) return `<h1>${renderInline(line.slice(2))}</h1>`
        if (line.startsWith('## ')) return `<h2>${renderInline(line.slice(3))}</h2>`
        return `<p>${renderInline(line).replaceAll('\n', '<br/>')}</p>`
      })
      .join('')
  }

  return html || '<p>...</p>'
}
