<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { useAuth } from '../auth'

const router = useRouter()
const { login } = useAuth()
const email = ref('')
const password = ref('')
const errorMessage = ref('')
const isSubmitting = ref(false)

async function submit(): Promise<void> {
  errorMessage.value = ''
  isSubmitting.value = true

  try {
    await login(email.value, password.value)
    await router.replace('/')
  } catch {
    errorMessage.value = '邮箱或密码错误，或登录状态无法验证。'
  } finally {
    isSubmitting.value = false
  }
}
</script>

<template>
  <main class="auth-shell">
    <section class="auth-card" aria-labelledby="login-title">
      <p class="eyebrow">M2 · Identity</p>
      <h1 id="login-title">登录 AfterCare AI</h1>
      <p class="subtitle">使用商家管理员账号继续。</p>

      <form class="login-form" @submit.prevent="submit">
        <label>
          邮箱
          <input v-model.trim="email" type="email" autocomplete="email" required />
        </label>
        <label>
          密码
          <input
            v-model="password"
            type="password"
            autocomplete="current-password"
            minlength="1"
            required
          />
        </label>
        <p v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</p>
        <button type="submit" :disabled="isSubmitting">
          {{ isSubmitting ? '正在登录…' : '登录' }}
        </button>
      </form>
    </section>
  </main>
</template>
