<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import api from '../api/client'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const email = ref('test@example.com')
const password = ref('secret123')
const displayName = ref('Tester')
const error = ref('')

const register = async () => {
  error.value = ''
  try {
    await api.post('/auth/register', {
      email: email.value,
      password: password.value,
      display_name: displayName.value,
    })
  } catch (e: any) {
    error.value = e.response?.data?.detail || '注册失败'
  }
}

const login = async () => {
  error.value = ''
  try {
    const res = await api.post('/auth/login', { email: email.value, password: password.value })
    authStore.setToken(res.data.access_token)
    router.push('/dashboard')
  } catch (e: any) {
    error.value = e.response?.data?.detail || '登录失败'
  }
}
</script>

<template>
  <main style="max-width: 420px; margin: 4rem auto; font-family: sans-serif">
    <h1>AI Language Learn</h1>
    <p>法语学习 MVP 登录</p>
    <input v-model="email" placeholder="email" style="width: 100%; margin: 6px 0; padding: 8px" />
    <input v-model="displayName" placeholder="display name" style="width: 100%; margin: 6px 0; padding: 8px" />
    <input
      v-model="password"
      type="password"
      placeholder="password"
      style="width: 100%; margin: 6px 0; padding: 8px"
    />
    <div style="display: flex; gap: 8px; margin-top: 10px">
      <button @click="register">注册</button>
      <button @click="login">登录</button>
    </div>
    <p v-if="error" style="color: #b00020">{{ error }}</p>
  </main>
</template>
