import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '../stores/auth'
import ChatView from '../views/ChatView.vue'
import KnowledgeView from '../views/KnowledgeView.vue'
import LoginView from '../views/LoginView.vue'
import MemoryView from '../views/MemoryView.vue'
import ModelSettingsView from '../views/ModelSettingsView.vue'
import PlanView from '../views/PlanView.vue'
import QuizView from '../views/QuizView.vue'
import WorkspaceView from '../views/WorkspaceView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/login', component: LoginView },
    {
      path: '/',
      component: WorkspaceView,
      children: [
        { path: '/chat', component: ChatView },
        { path: '/knowledge', component: KnowledgeView },
        { path: '/model-settings', component: ModelSettingsView },
        { path: '/quiz', component: QuizView },
        { path: '/memory', component: MemoryView },
        { path: '/plan', component: PlanView },
      ],
    },
  ],
})

router.beforeEach((to) => {
  const authStore = useAuthStore()
  const isLoginRoute = to.path === '/login'
  if (!isLoginRoute && !authStore.token) {
    return '/login'
  }
  if (isLoginRoute && authStore.token) {
    return '/chat'
  }
  return true
})

export default router
