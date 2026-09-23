<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import {
  createConversation,
  getConversation,
  listConversations,
  sendMessage,
  type Conversation,
  type ConversationDetail,
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

function showConversationLabel(conversation: Conversation): string {
  return `会话 · ${new Date(conversation.updated_at).toLocaleString('zh-CN')}`
}

async function loadConversation(conversationId: string): Promise<void> {
  selectedConversation.value = await getConversation(conversationId)
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
  try {
    selectedConversation.value = await sendMessage(selectedConversation.value.id, content)
    draft.value = ''
    await refreshConversations(false)
  } catch {
    errorMessage.value = '消息没有保存，请检查连接后重试。'
  } finally {
    isSending.value = false
  }
}

async function signOut(): Promise<void> {
  logout()
  await router.replace('/login')
}

onMounted(initialize)
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
          <button type="button" :disabled="isLoading" @click="startConversation">新建会话</button>
        </div>
        <p v-if="isLoading" class="muted">正在加载…</p>
        <p v-else-if="!conversations.length" class="muted">创建一个会话，开始咨询售后问题。</p>
        <button
          v-for="conversation in conversations"
          :key="conversation.id"
          type="button"
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
            </article>
          </div>
          <form class="message-form" @submit.prevent="submitMessage">
            <label for="message">消息</label>
            <textarea id="message" v-model="draft" :disabled="isSending" maxlength="4000" />
            <button type="submit" :disabled="isSending || !draft.trim()">
              {{ isSending ? '发送中…' : '发送' }}
            </button>
          </form>
        </template>
        <p v-else class="muted">请选择或创建一个会话。</p>
      </section>
    </section>
  </main>
</template>
