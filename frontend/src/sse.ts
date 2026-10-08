/**
 * 极简 SSE 解析工具（fetch + ReadableStream）。
 * 按空行分割事件块，解析 event: / data: 行；data: 后内容按 JSON 解析，失败则原样传字符串。
 */

export type SSEHandler = (event: string, data: unknown) => void

export async function parseSSE(resp: Response, onEvent: SSEHandler): Promise<void> {
  if (!resp.ok || !resp.body) {
    let detail = `HTTP ${resp.status}`
    try {
      const j = (await resp.json()) as { detail?: string }
      if (j && j.detail) detail = j.detail
    } catch { /* ignore */ }
    throw new Error(detail)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const handleBlock = (block: string) => {
    let event = 'message'
    const dataLines: string[] = []
    for (const rawLine of block.split('\n')) {
      const line = rawLine.replace(/\r$/, '')
      if (!line || line.startsWith(':')) continue
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''))
    }
    if (dataLines.length === 0) return
    const raw = dataLines.join('\n')
    let data: unknown = raw
    try { data = JSON.parse(raw) } catch { /* keep raw string */ }
    onEvent(event, data)
  }

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // 按空行（\n\n 或 \r\n\r\n 已归一）分割事件块
    for (;;) {
      const idx = buffer.search(/\n\s?\n/)
      if (idx < 0) break
      const block = buffer.slice(0, idx)
      buffer = buffer.slice(idx).replace(/^\n\s?\n/, '')
      handleBlock(block)
    }
  }
  buffer += decoder.decode()
  if (buffer.trim()) handleBlock(buffer)
}
