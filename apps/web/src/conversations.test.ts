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
})
