import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Message, ReplyStreamEvent } from '../conversations'
import HomeView from './HomeView.vue'

const api = vi.hoisted(() => ({
  createConversation: vi.fn(), getConversation: vi.fn(), listConversations: vi.fn(),
  regenerateMessage: vi.fn(), stopMessage: vi.fn(), streamMessage: vi.fn(),
  replace: vi.fn(), logout: vi.fn(),
}))
vi.mock('../conversations', () => api)
vi.mock('../auth', () => ({ useAuth: () => ({ currentUser: null, logout: api.logout }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ replace: api.replace }) }))

const conversation = { id: 'conversation', created_at: '2026-10-12T00:00:00Z', updated_at: '2026-10-12T00:00:00Z' }
const reply: Message = {
  id: 'reply', role: 'assistant', content: '', in_reply_to_message_id: 'user', reply_version: 1,
  generation_status: 'generating', is_current: false, created_at: conversation.created_at,
}
let wrapper: VueWrapper
let emit: (event: ReplyStreamEvent) => void
let signal: AbortSignal
let resolveStream: () => void
let rejectStream: (reason: Error) => void

function button(text: string) {
  return wrapper.findAll('button').find((item) => item.text() === text)!
}

beforeEach(async () => {
  vi.resetAllMocks()
  api.listConversations.mockResolvedValue([conversation, { ...conversation, id: 'another' }])
  api.getConversation.mockResolvedValue({ ...conversation, messages: [] })
  api.streamMessage.mockImplementation((_id, _content, callback, abortSignal) => {
    emit = callback
    signal = abortSignal
    emit({ type: 'started', message: { ...reply } })
    return new Promise<void>((resolve, reject) => {
      resolveStream = resolve
      rejectStream = reject
      signal.addEventListener('abort', () => reject(new Error('Aborted')), { once: true })
    })
  })
  wrapper = mount(HomeView)
  await flushPromises()
})

afterEach(() => wrapper.unmount())

async function send() {
  await wrapper.get('textarea').setValue('Hello')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
}

describe('reply lifecycle', () => {
  it('keeps streaming text intact and locks conversation switching during generation', async () => {
    await send()
    emit({ type: 'delta', message_id: reply.id, content: 'Placeholder' })
    emit({ type: 'delta', message_id: reply.id, content: ' reply: Hello' })
    await flushPromises()
    expect(wrapper.text()).toContain('Placeholder reply: Hello')
    expect(button('新建会话').attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('.conversation-button').every((item) => item.attributes('disabled') !== undefined)).toBe(true)
    await wrapper.findAll('.conversation-button')[1].trigger('click')
    expect(api.getConversation).toHaveBeenCalledTimes(1)
  })

  it('stops the originating reply and aborts its connection', async () => {
    await send()
    api.stopMessage.mockResolvedValue({ ...reply, generation_status: 'cancelled' })
    await button('停止生成').trigger('click')
    await flushPromises()
    expect(api.stopMessage).toHaveBeenCalledWith('conversation', 'reply')
    expect(signal.aborted).toBe(true)
    expect(wrapper.find('textarea').attributes('disabled')).toBeUndefined()
  })

  it('clears sending state even if reloading persisted history fails', async () => {
    await send()
    api.getConversation.mockRejectedValueOnce(new Error('Offline'))
    resolveStream()
    await flushPromises()
    expect(wrapper.text()).toContain('无法重新读取消息')
    expect(wrapper.find('textarea').attributes('disabled')).toBeUndefined()
    expect(button('新建会话').attributes('disabled')).toBeUndefined()
  })

  it('reports an interrupted stream and permits retry', async () => {
    await send()
    rejectStream(new Error('REPLY_STREAM_INCOMPLETE'))
    await flushPromises()
    expect(wrapper.text()).toContain('消息流已中断')
    expect(wrapper.find('textarea').attributes('disabled')).toBeUndefined()
  })

  it('aborts on unmount without reloading the disposed view', async () => {
    await send()
    wrapper.unmount()
    await flushPromises()
    expect(signal.aborted).toBe(true)
    expect(api.getConversation).toHaveBeenCalledTimes(1)
  })

  it('aborts before logging out and does not reload with revoked credentials', async () => {
    await send()
    await button('退出登录').trigger('click')
    await flushPromises()
    expect(signal.aborted).toBe(true)
    expect(api.logout).toHaveBeenCalledOnce()
    expect(api.replace).toHaveBeenCalledWith('/login')
    expect(api.getConversation).toHaveBeenCalledTimes(1)
  })

  it('switches the current marker only when the regenerated version completes', async () => {
    api.getConversation.mockResolvedValue({
      ...conversation, messages: [{ ...reply, content: 'Original', generation_status: 'completed', is_current: true }],
    })
    await wrapper.findAll('.conversation-button')[0].trigger('click')
    await flushPromises()
    api.regenerateMessage.mockImplementation((_id, _message, callback, abortSignal) => {
      emit = callback
      signal = abortSignal
      return new Promise<void>((resolve, reject) => {
        resolveStream = resolve
        signal.addEventListener('abort', () => reject(new Error('Aborted')), { once: true })
      })
    })
    await button('重新生成').trigger('click')
    emit({ type: 'started', message: { ...reply, id: 'new', reply_version: 2 } })
    await flushPromises()
    expect(wrapper.findAll('article')[0].text()).not.toContain('历史版本')
    emit({ type: 'completed', message: {
      ...reply, id: 'new', reply_version: 2, content: 'New', generation_status: 'completed', is_current: true,
    } })
    await flushPromises()
    expect(wrapper.findAll('article')[0].text()).toContain('历史版本')
    expect(wrapper.findAll('article').find((item) => item.text().includes('New'))?.text()).not.toContain('历史版本')
  })
})
