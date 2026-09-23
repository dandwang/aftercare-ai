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
