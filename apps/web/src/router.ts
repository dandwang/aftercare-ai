import { createRouter, createWebHistory } from 'vue-router'

import { useAuth } from './auth'
import HomeView from './views/HomeView.vue'
import LoginView from './views/LoginView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: HomeView, meta: { requiresAuth: true } },
    { path: '/login', component: LoginView },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuth()
  const isAuthenticated = await auth.restoreSession()

  if (to.meta.requiresAuth && !isAuthenticated) return { path: '/login' }
  if (to.path === '/login' && isAuthenticated) return { path: '/' }
  return true
})
