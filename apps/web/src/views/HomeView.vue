<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  createConversation,
  getConversation,
  listConversations,
  regenerateMessage,
  stopMessage,
  submitFeedback,
  streamMessage,
  type Conversation,
  type ConversationDetail,
  type Message,
  type MessageFeedback,
  type ReplyStreamEvent,
} from '../conversations'
import { useAuth } from '../auth'

const router = useRouter()
const { currentUser, logout } = useAuth()
const conversations = ref<Conversation[]>([])
const selectedConversation = ref<ConversationDetail | null>(null)
const draft = ref('')
const isLoading = ref(true)
const isSending = ref(false)
const errorMessage = ref('')
const activeReplyId = ref<string | null>(null)
const feedbackMessageId = ref<string | null>(null)
const feedbackReason = ref<MessageFeedback['reason']>('incorrect')
const feedbackDetail = ref('')
const isSavingFeedback = ref(false)
let streamController: AbortController | null = null
let activeConversationId: string | null = null
let disposed = false
let conversationLoadId = 0

function showConversationLabel(conversation: Conversation): string {
  return `会话 · ${new Date(conversation.updated_at).toLocaleString('zh-CN')}`
}

function feedbackFor(messageId: string): MessageFeedback | undefined {
  return selectedConversation.value?.feedback?.find((feedback) => feedback.message_id === messageId)
}

function contextFor(messageId: string) {
  return selectedConversation.value?.contexts?.find((context) => context.message_id === messageId)
}

function editDislike(message: Message): void {
  feedbackMessageId.value = message.id
  const feedback = feedbackFor(message.id)
  feedbackReason.value = feedback?.reason ?? 'incorrect'
  feedbackDetail.value = feedback?.detail ?? ''
}

async function saveFeedback(messageId: string, rating: MessageFeedback['rating']): Promise<void> {
  const conversation = selectedConversation.value
  if (!conversation || isSavingFeedback.value) return
  isSavingFeedback.value = true
  try {
    const saved = await submitFeedback(conversation.id, messageId, rating,
      rating === 'dislike' ? feedbackReason.value : null,
      rating === 'dislike' ? feedbackDetail.value : '')
    if (!disposed && selectedConversation.value?.id === conversation.id) {
      const feedback = conversation.feedback ?? []
      conversation.feedback = [...feedback.filter((item) => item.message_id !== messageId), saved]
      feedbackMessageId.value = null
    }
  } catch {
    errorMessage.value = '无法保存反馈，请稍后重试。'
  } finally {
    isSavingFeedback.value = false
  }
}

async function loadConversation(conversationId: string): Promise<void> {
  const loadId = ++conversationLoadId
  const conversation = await getConversation(conversationId)
  if (!disposed && loadId === conversationLoadId &&
    (!isSending.value || activeConversationId === conversationId)) {
    selectedConversation.value = conversation
  }
}

async function refreshConversations(selectNewest = true): Promise<void> {
  conversations.value = await listConversations()
  if (selectNewest && conversations.value[0]) await loadConversation(conversations.value[0].id)
}

async function initialize(): Promise<void> {
  isLoading.value = true
  errorMessage.value = ''
  try {
    await refreshConversations()
  } catch {
    errorMessage.value = '无法读取会话，请确认登录状态和服务连接。'
  } finally {
    isLoading.value = false
  }
}

async function startConversation(): Promise<void> {
  if (isSending.value) return
  errorMessage.value = ''
  try {
    const conversation = await createConversation()
    await refreshConversations(false)
    await loadConversation(conversation.id)
  } catch {
    errorMessage.value = '无法创建会话，请稍后重试。'
  }
}

async function selectConversation(conversationId: string): Promise<void> {
  if (isSending.value) return
  errorMessage.value = ''
  try {
    await loadConversation(conversationId)
  } catch {
    errorMessage.value = '无法读取该会话。'
  }
}

async function submitMessage(): Promise<void> {
  const content = draft.value.trim()
  if (!content || !selectedConversation.value || isSending.value) return

  isSending.value = true
  errorMessage.value = ''
  const conversationId = selectedConversation.value.id
  activeConversationId = conversationId
  selectedConversation.value.messages.push({
    id: `pending-user-${Date.now()}`,
    role: 'user',
    content,
    in_reply_to_message_id: null,
    reply_version: null,
    generation_status: 'completed',
    is_current: true,
    created_at: new Date().toISOString(),
  })
  draft.value = ''
  const controller = new AbortController()
  streamController = controller
  try {
    await streamMessage(conversationId, content,
      (event) => applyReplyEvent(conversationId, event), controller.signal)
    if (!disposed) await refreshConversations(false)
  } catch {
    if (!disposed && !controller.signal.aborted) errorMessage.value = '消息流已中断，请检查连接后重试。'
  } finally {
    await finishStream(conversationId)
  }
}

async function finishStream(conversationId: string): Promise<void> {
  try {
    if (!disposed) await loadConversation(conversationId)
  } catch {
    if (!disposed) errorMessage.value = '无法重新读取消息，请检查连接后刷新。'
  } finally {
    streamController = null
    activeConversationId = null
    activeReplyId.value = null
    isSending.value = false
  }
}

function applyReplyEvent(conversationId: string, event: ReplyStreamEvent): void {
  if (disposed || selectedConversation.value?.id !== conversationId) return
  if (event.type === 'started') {
    activeReplyId.value = event.message.id
    selectedConversation.value.messages.push(event.message)
    return
  }
  if (event.type === 'delta') {
    const message = selectedConversation.value.messages.find((item) => item.id === event.message_id)
    if (message) message.content += event.content
    return
  }
  const index = selectedConversation.value.messages.findIndex((item) => item.id === event.message.id)
  if (index >= 0) selectedConversation.value.messages[index] = event.message
  if (event.type === 'completed') {
    for (const message of selectedConversation.value.messages) {
      if (message.role === 'assistant' && message.id !== event.message.id &&
        message.in_reply_to_message_id === event.message.in_reply_to_message_id) message.is_current = false
    }
  }
}

async function stopGenerating(): Promise<void> {
  if (!activeConversationId || !activeReplyId.value) return
  const controller = streamController
  try {
    await stopMessage(activeConversationId, activeReplyId.value)
    controller?.abort()
  } catch {
    errorMessage.value = '无法停止生成，请稍后重试。'
  }
}

async function regenerate(message: Message): Promise<void> {
  if (!selectedConversation.value || isSending.value || message.generation_status !== 'completed') return
  isSending.value = true
  errorMessage.value = ''
  const conversationId = selectedConversation.value.id
  activeConversationId = conversationId
  const controller = new AbortController()
  streamController = controller
  try {
    await regenerateMessage(conversationId, message.id,
      (event) => applyReplyEvent(conversationId, event), controller.signal)
    if (!disposed) await refreshConversations(false)
  } catch {
    if (!disposed && !controller.signal.aborted) errorMessage.value = '无法重新生成回复，请稍后重试。'
  } finally {
    await finishStream(conversationId)
  }
}

async function signOut(): Promise<void> {
  disposed = true
  streamController?.abort()
  logout()
  await router.replace('/login')
}

onMounted(initialize)
onBeforeUnmount(() => {
  disposed = true
  streamController?.abort()
})
</script>

<template>
  <main class="shell">
    <section class="hero">
      <div class="top-row">
        <div>
          <p class="eyebrow">M2 · Conversations</p>
          <h1>AfterCare AI</h1>
          <p class="subtitle">{{ currentUser?.tenant_name }} · {{ currentUser?.role }}</p>
        </div>
        <button type="button" class="secondary-button" @click="signOut">退出登录</button>
      </div>
      <p class="signed-in-as">当前账号：{{ currentUser?.email }}</p>
    </section>

    <p v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</p>

    <section class="chat-layout" aria-label="会话">
      <aside class="conversation-list">
        <div class="panel-heading">
          <h2>会话</h2>
          <button type="button" :disabled="isLoading || isSending" @click="startConversation">新建会话</button>
        </div>
        <p v-if="isLoading" class="muted">正在加载…</p>
        <p v-else-if="!conversations.length" class="muted">创建一个会话，开始咨询售后问题。</p>
        <button
          v-for="conversation in conversations"
          :key="conversation.id"
          type="button"
          :disabled="isSending"
          :class="['conversation-button', { selected: selectedConversation?.id === conversation.id }]"
          @click="selectConversation(conversation.id)"
        >
          {{ showConversationLabel(conversation) }}
        </button>
      </aside>

      <section class="message-panel" aria-live="polite">
        <template v-if="selectedConversation">
          <div class="message-list">
            <p v-if="!selectedConversation.messages.length" class="muted">发送第一条消息开始对话。</p>
            <article
              v-for="message in selectedConversation.messages"
              :key="message.id"
              :class="['message', message.role]"
            >
              <strong>{{ message.role === 'user' ? '你' : 'AfterCare AI' }}</strong>
              <p>{{ message.content }}</p>
              <small v-if="message.role === 'assistant'">
                {{ message.generation_status === 'generating' ? '正在生成…' : message.generation_status }}
                <template v-if="message.reply_version"> · 版本 {{ message.reply_version }}</template>
                <template v-if="message.reply_version && !message.is_current && message.generation_status === 'completed'"> · 历史版本</template>
              </small>
              <button
                v-if="message.role === 'assistant' && message.generation_status === 'completed'"
                type="button"
                class="secondary-button"
                :disabled="isSending"
                @click="regenerate(message)"
              >
                重新生成
              </button>
              <div v-if="message.role === 'assistant' && message.generation_status === 'completed'" class="feedback-row">
                <button type="button" class="secondary-button" :disabled="isSending || isSavingFeedback"
                  :aria-pressed="feedbackFor(message.id)?.rating === 'like'" @click="saveFeedback(message.id, 'like')">点赞</button>
                <button type="button" class="secondary-button" :disabled="isSending || isSavingFeedback"
                  :aria-pressed="feedbackFor(message.id)?.rating === 'dislike'" @click="editDislike(message)">点踩</button>
                <small v-if="feedbackFor(message.id)">已保存{{ feedbackFor(message.id)?.rating === 'like' ? '点赞' : '点踩' }} · 版本 {{ message.reply_version }}</small>
              </div>
              <div v-if="feedbackMessageId === message.id" class="feedback-editor">
                <label :for="`feedback-reason-${message.id}`">反馈原因</label>
                <select :id="`feedback-reason-${message.id}`" v-model="feedbackReason" :disabled="isSavingFeedback">
                  <option value="incorrect">信息不准确</option>
                  <option value="irrelevant">没有回答问题</option>
                  <option value="unclear">表达不清楚</option>
                  <option value="other">其他</option>
                </select>
                <label :for="`feedback-detail-${message.id}`">补充说明（可选）</label>
                <textarea :id="`feedback-detail-${message.id}`" v-model="feedbackDetail" maxlength="500" :disabled="isSavingFeedback" />
                <button type="button" :disabled="isSavingFeedback" @click="saveFeedback(message.id, 'dislike')">保存反馈</button>
              </div>
              <details v-if="contextFor(message.id)" class="context-details">
                <summary>本次上下文 · 输入 {{ contextFor(message.id)?.input_token_count }} Token</summary>
                <p>总预算 {{ contextFor(message.id)?.total_token_budget }}，预留输出 {{ contextFor(message.id)?.output_token_limit }} Token。</p>
                <p>使用 {{ contextFor(message.id)?.selected_message_ids.length }} 条消息{{ contextFor(message.id)?.summary ? '和历史摘要' : '' }}。</p>
                <template v-if="contextFor(message.id)?.summary">
                  <strong>保留的历史事实（用户陈述）</strong>
                  <ul>
                    <li v-for="(fact, index) in contextFor(message.id)?.summary?.facts" :key="index">{{ fact.excerpt }}</li>
                  </ul>
                  <p v-if="!contextFor(message.id)?.summary?.facts.length">已保留近期历史摘录。</p>
                </template>
              </details>
            </article>
          </div>
          <form class="message-form" @submit.prevent="submitMessage">
            <label for="message">消息</label>
            <textarea id="message" v-model="draft" :disabled="isSending" maxlength="4000" />
            <button v-if="isSending" type="button" @click="stopGenerating">停止生成</button>
            <button v-else type="submit" :disabled="!draft.trim()">
              发送
            </button>
          </form>
        </template>
        <p v-else class="muted">请选择或创建一个会话。</p>
      </section>
    </section>
  </main>
</template>
