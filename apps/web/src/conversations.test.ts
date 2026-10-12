import { afterEach, describe, expect, it, vi } from 'vitest'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

async function loadConversationApi() {
  vi.resetModules()
  sessionStorage.setItem('aftercare.access-token', 'test-token')
  return import('./conversations')
}

afterEach(() => {
  sessionStorage.clear()
  vi.unstubAllGlobals()
})

describe('conversation API client', () => {
  it('sends the session token and returns persisted message history', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        id: 'a72e1c0c-4efc-44b8-bb63-6694c6d8c1bd',
        created_at: '2026-09-23T00:00:00Z',
        updated_at: '2026-09-23T00:00:01Z',
        messages: [
          {
            id: 'b72e1c0c-4efc-44b8-bb63-6694c6d8c1bd',
            role: 'user',
            content: 'Where is my order?',
            created_at: '2026-09-23T00:00:00Z',
          },
        ],
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const { sendMessage } = await loadConversationApi()

    const conversation = await sendMessage('a72e1c0c-4efc-44b8-bb63-6694c6d8c1bd', 'Where is my order?')

    expect(conversation.messages[0].content).toBe('Where is my order?')
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/conversations/a72e1c0c-4efc-44b8-bb63-6694c6d8c1bd/messages',
      expect.objectContaining({ method: 'POST', headers: expect.any(Headers) }),
    )
  })

  it('rejects a failed conversation request', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 404 })))
    const { getConversation } = await loadConversationApi()

    await expect(getConversation('a72e1c0c-4efc-44b8-bb63-6694c6d8c1bd')).rejects.toThrow(
      'CONVERSATION_REQUEST_FAILED_404',
    )
  })

  it('parses streamed lifecycle events from an authenticated POST request', async () => {
    const message = {
      id: 'b72e1c0c-4efc-44b8-bb63-6694c6d8c1bd',
      role: 'assistant',
      content: 'Placeholder reply: Hello',
      in_reply_to_message_id: 'c72e1c0c-4efc-44b8-bb63-6694c6d8c1bd',
      reply_version: 1,
      generation_status: 'completed',
      is_current: true,
      created_at: '2026-09-23T00:00:00Z',
    }
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          `event: started\ndata: ${JSON.stringify({ message: { ...message, content: '' } })}\n\n` +
            `event: delta\ndata: ${JSON.stringify({ message_id: message.id, content: 'Hello' })}\n\n` +
            `event: completed\ndata: ${JSON.stringify({ message })}\n\n`,
          { headers: { 'Content-Type': 'text/event-stream' } },
        ),
      ),
    )
    const { streamMessage } = await loadConversationApi()
    const events: string[] = []

    await streamMessage(
      'a72e1c0c-4efc-44b8-bb63-6694c6d8c1bd',
      'Hello',
      (event) => events.push(event.type),
      new AbortController().signal,
    )

    expect(events).toEqual(['started', 'delta', 'completed'])
  })

  it('rejects EOF without a terminal event and releases the reader', async () => {
    const response = new Response('event: started\ndata: {"message":{"id":"reply"}}\n\n')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
    const { streamMessage } = await loadConversationApi()
    await expect(streamMessage('conversation', 'Hello', () => {}, new AbortController().signal))
      .rejects.toThrow('REPLY_STREAM_INCOMPLETE')
    expect(response.body?.locked).toBe(false)
  })

  it('parses byte-fragmented UTF-8 frames and cancels after the terminal event', async () => {
    const message = { id: 'reply', content: '订单' }
    const bytes = new TextEncoder().encode(
      `event: started\ndata: ${JSON.stringify({ message })}\n\n` +
      `event: delta\ndata: ${JSON.stringify({ message_id: 'reply', content: '订单' })}\n\n` +
      `event: cancelled\ndata: ${JSON.stringify({ message })}\n\n`,
    )
    const cancel = vi.fn()
    const response = new Response(new ReadableStream({
      start(controller) {
        for (const byte of bytes) controller.enqueue(new Uint8Array([byte]))
      },
      cancel,
    }))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
    const { streamMessage } = await loadConversationApi()
    const events: string[] = []
    await streamMessage('conversation', 'Hello', (event) => {
      events.push(event.type === 'delta' ? event.content : event.type)
    }, new AbortController().signal)
    expect(events).toEqual(['started', '订单', 'cancelled'])
    expect(cancel).toHaveBeenCalledOnce()
    expect(response.body?.locked).toBe(false)
  })

  it('rejects events for another reply and cancels the underlying stream', async () => {
    const cancel = vi.fn()
    const response = new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(
          'event: started\ndata: {"message":{"id":"reply"}}\n\n' +
          'event: delta\ndata: {"message_id":"another","content":"wrong"}\n\n',
        ))
      },
      cancel,
    }))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
    const { streamMessage } = await loadConversationApi()
    await expect(streamMessage('conversation', 'Hello', () => {}, new AbortController().signal))
      .rejects.toThrow('REPLY_STREAM_INVALID_SEQUENCE')
    expect(cancel).toHaveBeenCalledOnce()
    expect(response.body?.locked).toBe(false)
  })

  it('posts feedback against the concrete reply id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      id: 'feedback', message_id: 'reply-v1', rating: 'dislike', reason: 'unclear', detail: 'More detail',
    }))
    vi.stubGlobal('fetch', fetchMock)
    const { submitFeedback } = await loadConversationApi()
    const saved = await submitFeedback('conversation', 'reply-v1', 'dislike', 'unclear', 'More detail')
    expect(saved.message_id).toBe('reply-v1')
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/conversations/conversation/messages/reply-v1/feedback',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ rating: 'dislike', reason: 'unclear', detail: 'More detail' }) }),
    )
  })
})
