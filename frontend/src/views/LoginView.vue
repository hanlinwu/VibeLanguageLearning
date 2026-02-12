<script setup lang="ts">
import { reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import api from '../api/client'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const form = reactive({
  email: 'test@example.com',
  display_name: 'Tester',
  password: 'secret123',
})

const login = async () => {
  try {
    const res = await api.post('/auth/login', { email: form.email, password: form.password })
    authStore.setToken(res.data.access_token)
    ElMessage.success('登录成功')
    await router.push('/chat')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '登录失败')
  }
}

const register = async () => {
  try {
    await api.post('/auth/register', {
      email: form.email,
      password: form.password,
      display_name: form.display_name,
    })
    ElMessage.success('注册成功，正在登录')
    await login()
  } catch (e: any) {
    const detail = e.response?.data?.detail
    if (detail === 'Email already registered') {
      ElMessage.warning('账号已存在，正在直接登录')
      await login()
      return
    }
    ElMessage.error(detail || '注册失败')
  }
}
</script>

<template>
  <div class="login-page">
    <el-card class="login-card" shadow="hover">
      <template #header>
        <div class="login-title">French AI Tutor</div>
      </template>
      <el-form label-position="top">
        <el-form-item label="邮箱">
          <el-input v-model="form.email" placeholder="请输入邮箱" />
        </el-form-item>
        <el-form-item label="显示名称">
          <el-input v-model="form.display_name" placeholder="请输入显示名称" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password placeholder="请输入密码" />
        </el-form-item>
        <div class="login-actions">
          <el-button type="warning" plain @click="register">注册</el-button>
          <el-button type="primary" @click="login">登录</el-button>
        </div>
      </el-form>
    </el-card>
  </div>
</template>
