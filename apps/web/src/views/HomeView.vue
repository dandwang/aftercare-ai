<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useAuth } from '../auth'

type HealthState = 'checking' | 'healthy' | 'unhealthy'

interface ServiceStatus {
  status: 'healthy' | 'unhealthy'
}

interface ReadinessResponse {
  status: 'ready' | 'not_ready'
  services: Record<string, ServiceStatus>
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const router = useRouter()
const { currentUser, logout } = useAuth()
const apiState = ref<HealthState>('checking')
const readinessState = ref<HealthState>('checking')
const services = ref<Record<string, ServiceStatus>>({})
const lastCheckedAt = ref<Date | null>(null)

const systemState = computed<HealthState>(() => {
  if (apiState.value === 'checking' || readinessState.value === 'checking') return 'checking'
  if (apiState.value === 'unhealthy' || readinessState.value === 'unhealthy') return 'unhealthy'
  return 'healthy'
})

const statusLabel = computed(() => {
  if (systemState.value === 'checking') return '检查中'
  return systemState.value === 'healthy' ? '就绪' : '未就绪'
})

async function refreshHealth(): Promise<void> {
  apiState.value = 'checking'
  readinessState.value = 'checking'
  services.value = {}

  try {
    const response = await fetch(`${apiBaseUrl}/health/live`)
    apiState.value = response.ok ? 'healthy' : 'unhealthy'
  } catch {
    apiState.value = 'unhealthy'
  }

  try {
    const response = await fetch(`${apiBaseUrl}/health/ready`)
    const body = (await response.json()) as ReadinessResponse
    services.value = body.services ?? {}
    readinessState.value = response.ok && body.status === 'ready' ? 'healthy' : 'unhealthy'
  } catch {
    readinessState.value = 'unhealthy'
  } finally {
    lastCheckedAt.value = new Date()
  }
}

async function signOut(): Promise<void> {
  logout()
  await router.replace('/login')
}

onMounted(refreshHealth)
</script>

<template>
  <main class="shell">
    <section class="hero">
      <div class="top-row">
        <div>
          <p class="eyebrow">M2 · Identity</p>
          <h1>AfterCare AI</h1>
          <p class="subtitle">{{ currentUser?.tenant_name }} · {{ currentUser?.role }}</p>
        </div>
        <button type="button" class="secondary-button" @click="signOut">退出登录</button>
      </div>
      <p class="signed-in-as">当前账号：{{ currentUser?.email }}</p>
    </section>

    <section class="status-panel" aria-live="polite">
      <div class="panel-heading">
        <div>
          <p class="panel-label">系统状态</p>
          <h2 :class="['overall-status', systemState]">{{ statusLabel }}</h2>
        </div>
        <button type="button" :disabled="systemState === 'checking'" @click="refreshHealth">
          {{ systemState === 'checking' ? '正在检查…' : '重新检查' }}
        </button>
      </div>

      <div class="service-grid">
        <article class="service-card">
          <span>API</span>
          <strong :class="apiState">{{ apiState === 'healthy' ? 'Healthy' : apiState }}</strong>
        </article>
        <article v-for="(service, name) in services" :key="name" class="service-card">
          <span>{{ name }}</span>
          <strong :class="service.status">{{ service.status }}</strong>
        </article>
      </div>

      <p v-if="lastCheckedAt" class="timestamp">
        最近检查：{{ lastCheckedAt.toLocaleTimeString('zh-CN') }}
      </p>
    </section>
  </main>
</template>
