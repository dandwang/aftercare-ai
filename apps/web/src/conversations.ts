import { authenticatedFetch } from './auth'

export interface Conversation {
  id: string
  created_at: string
  updated_at: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  in_reply_to_message_id: string | null
  reply_version: number | null
  generation_status: 'completed' | 'generating' | 'cancelled'
  is_current: boolean
  created_at: string
}

export interface ConversationDetail extends Conversation {
  messages: Message[]
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`CONVERSATION_REQUEST_FAILED_${response.status}`)
  return (await response.json()) as T
}

export async function listConversations(): Promise<Conversation[]> {
  return parseResponse<Conversation[]>(await authenticatedFetch('/api/v1/conversations'))
}

export async function createConversation(): Promise<Conversation> {
  return parseResponse<Conversation>(
    await authenticatedFetch('/api/v1/conversations', { method: 'POST' }),
  )
}

export async function getConversation(conversationId: string): Promise<ConversationDetail> {
  return parseResponse<ConversationDetail>(
    await authenticatedFetch(`/api/v1/conversations/${conversationId}`),
  )
}

export async function sendMessage(
  conversationId: string,
  content: string,
): Promise<ConversationDetail> {
  return parseResponse<ConversationDetail>(
    await authenticatedFetch(`/api/v1/conversations/${conversationId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    }),
  )
}

export type ReplyStreamEvent =
  | { type: 'started'; message: Message }
  | { type: 'delta'; message_id: string; content: string }
  | { type: 'completed' | 'cancelled'; message: Message }

function parseSseFrame(frame: string): ReplyStreamEvent | null {
  const event = frame.match(/^event: (.+)$/m)?.[1]
  const data = frame.match(/^data: (.+)$/m)?.[1]
  if (!event || !data) return null
  const payload = JSON.parse(data) as { message?: Message; message_id?: string; content?: string }
  if (event === 'started' && payload.message) return { type: 'started', message: payload.message }
  if (event === 'delta' && payload.message_id && typeof payload.content === 'string') {
    return { type: 'delta', message_id: payload.message_id, content: payload.content }
  }
  if ((event === 'completed' || event === 'cancelled') && payload.message) {
    return { type: event, message: payload.message }
  }
  return null
}

async function consumeReplyStream(
  response: Response,
  onEvent: (event: ReplyStreamEvent) => void,
): Promise<void> {
  if (!response.ok || !response.body) throw new Error(`CONVERSATION_REQUEST_FAILED_${response.status}`)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      const event = parseSseFrame(frame)
      if (event) onEvent(event)
    }
    if (done) return
  }
}

export async function streamMessage(
  conversationId: string,
  content: string,
  onEvent: (event: ReplyStreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  await consumeReplyStream(
    await authenticatedFetch(`/api/v1/conversations/${conversationId}/messages/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
      signal,
    }),
    onEvent,
  )
}

export async function regenerateMessage(
  conversationId: string,
  messageId: string,
  onEvent: (event: ReplyStreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  await consumeReplyStream(
    await authenticatedFetch(
      `/api/v1/conversations/${conversationId}/messages/${messageId}/regenerate/stream`,
      { method: 'POST', signal },
    ),
    onEvent,
  )
}

export async function stopMessage(conversationId: string, messageId: string): Promise<Message> {
  return parseResponse<Message>(
    await authenticatedFetch(`/api/v1/conversations/${conversationId}/messages/${messageId}/stop`, {
      method: 'POST',
    }),
  )
}
