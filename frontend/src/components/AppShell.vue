<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ChatDotRound,
  CollectionTag,
  DataAnalysis,
  Calendar,
  Setting,
  MoreFilled,
  UserFilled,
  SwitchButton,
} from '@element-plus/icons-vue'

import api from '../api/client'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const userName = ref('当前用户')
const userEmail = ref('')

const navItems = [
  { to: '/chat', label: 'AI 对话', icon: ChatDotRound },
  { to: '/quiz', label: '练习', icon: CollectionTag },
  { to: '/memory', label: '进展', icon: DataAnalysis },
  { to: '/plan', label: '计划', icon: Calendar },
]

const adminItems = [{ to: '/knowledge', label: '知识库管理', icon: Setting }]

const activePath = computed(() => route.path)
const isChatRoute = computed(() => route.path === '/chat')

const logout = async () => {
  authStore.clear()
  ElMessage.success('已退出登录')
  await router.push('/login')
}

const openSettings = () => {
  ElMessage.info('设置功能正在完善中')
}

const loadCurrentUser = async () => {
  try {
    const res = await api.get('/auth/me')
    userName.value = res.data.display_name || '当前用户'
    userEmail.value = res.data.email || ''
  } catch {
    userName.value = '当前用户'
    userEmail.value = ''
  }
}

onMounted(() => {
  void loadCurrentUser()
})
</script>

<template>
  <el-container class="shell-container">
    <el-aside width="250px" class="shell-aside">
      <div class="brand">French AI Tutor</div>
      <div class="shell-nav">
        <div class="nav-section-title">学习功能</div>
        <el-menu :default-active="activePath" class="side-menu" router>
          <el-menu-item v-for="item in navItems" :key="item.to" :index="item.to">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </el-menu-item>
        </el-menu>
      </div>

      <div class="shell-bottom">
        <div class="nav-section-title nav-section-title--admin">高级后台</div>
        <el-menu :default-active="activePath" class="side-menu side-menu--admin" router>
          <el-menu-item v-for="item in adminItems" :key="item.to" :index="item.to">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </el-menu-item>
        </el-menu>

        <div class="user-panel">
          <el-avatar :icon="UserFilled" size="small" />
          <div class="user-meta">
            <div class="user-name">{{ userName }}</div>
            <div class="user-email">{{ userEmail }}</div>
          </div>
          <el-dropdown trigger="click">
            <el-button text class="user-more-btn">
              <el-icon><MoreFilled /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="openSettings">
                  <el-icon><Setting /></el-icon>
                  <span>设置</span>
                </el-dropdown-item>
                <el-dropdown-item divided @click="logout">
                  <el-icon><SwitchButton /></el-icon>
                  <span>退出登录</span>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </el-aside>
    <el-main :class="['shell-main', { 'shell-main--chat': isChatRoute }]">
      <slot />
    </el-main>
  </el-container>
</template>
