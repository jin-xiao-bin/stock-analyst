/**
 * 极简 markdown → html 渲染（无外部依赖）。
 * 支持：标题、粗体、行内代码、代码块、无序/有序列表、引用、换行。
 */

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function inline(s: string): string {
  let r = escapeHtml(s)
  r = r.replace(/`([^`]+)`/g, '<code>$1</code>')
  r = r.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  r = r.replace(/\*([^*]+)\*/g, '<em>$1</em>')
  return r
}

export function md2html(md: string): string {
  const lines = md.replace(/\r\n/g, '\n').split('\n')
  const out: string[] = []
  let inCode = false
  let listType: 'ul' | 'ol' | null = null
  let inQuote = false

  const closeList = () => {
    if (listType) { out.push(`</${listType}>`); listType = null }
  }
  const closeQuote = () => {
    if (inQuote) { out.push('</blockquote>'); inQuote = false }
  }

  for (const line of lines) {
    if (line.trim().startsWith('```')) {
      if (inCode) {
        out.push('</code></pre>')
        inCode = false
      } else {
        closeList(); closeQuote()
        out.push('<pre><code>')
        inCode = true
      }
      continue
    }
    if (inCode) { out.push(escapeHtml(line)); continue }

    const t = line.trim()
    if (!t) { closeList(); closeQuote(); continue }

    const h = /^(#{1,6})\s+(.*)$/.exec(t)
    if (h) {
      closeList(); closeQuote()
      const level = h[1].length
      out.push(`<h${level}>${inline(h[2])}</h${level}>`)
      continue
    }

    const ul = /^[-*+]\s+(.*)$/.exec(t)
    if (ul) {
      closeQuote()
      if (listType !== 'ul') { closeList(); out.push('<ul>'); listType = 'ul' }
      out.push(`<li>${inline(ul[1])}</li>`)
      continue
    }

    const ol = /^\d+[.、]\s+(.*)$/.exec(t)
    if (ol) {
      closeQuote()
      if (listType !== 'ol') { closeList(); out.push('<ol>'); listType = 'ol' }
      out.push(`<li>${inline(ol[1])}</li>`)
      continue
    }

    const q = /^&gt;\s?(.*)$/.exec(line) || /^>\s?(.*)$/.exec(t)
    if (q) {
      closeList()
      if (!inQuote) { out.push('<blockquote>'); inQuote = true }
      out.push(`<p>${inline(q[1])}</p>`)
      continue
    }

    closeList(); closeQuote()
    out.push(`<p>${inline(t)}</p>`)
  }
  if (inCode) out.push('</code></pre>')
  closeList(); closeQuote()
  return out.join('\n')
}
