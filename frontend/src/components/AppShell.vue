<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ChatDotRound,
  Clock,
  CollectionTag,
  DataAnalysis,
  Calendar,
  Setting,
  MoreFilled,
  UserFilled,
  SwitchButton,
} from '@element-plus/icons-vue'
import { storeToRefs } from 'pinia'

import api from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useChatStore, type ConversationItem } from '../stores/chat'
import yanzhouLogo from '../assets/yanzhou-logo.svg'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const chatStore = useChatStore()
const { conversations, activeConversationId } = storeToRefs(chatStore)
const userName = ref('当前用户')
const userEmail = ref('')
const userAvatarUrl = ref('')
const isAdmin = ref(false)
const profileDialogVisible = ref(false)
const profileSaving = ref(false)
const avatarRegenerating = ref(false)
const profileDisplayName = ref('')
const profileAvatarUrl = ref('')

const navItems = [
  { to: '/chat', label: '首页', icon: ChatDotRound },
  { to: '/quiz', label: '练习', icon: CollectionTag },
  { to: '/memory', label: '进展', icon: DataAnalysis },
  { to: '/plan', label: '计划', icon: Calendar },
]

const adminItems = [{ to: '/knowledge', label: '知识库管理', icon: Setting }]

const activePath = computed(() => route.path)
const isChatRoute = computed(() => route.path === '/chat')
const MS_PER_DAY = 24 * 60 * 60 * 1000

const parseConversationTimestamp = (value: string): number => {
  // Backend uses utcnow().isoformat() (no timezone suffix). Treat as UTC.
  const normalized = /[zZ]$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`
  return new Date(normalized).getTime()
}

const groupedConversations = computed(() => {
  const now = new Date()
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const todayItems: ConversationItem[] = []
  const within30DaysItems: ConversationItem[] = []
  const olderByMonth = new Map<string, { label: string; sortKey: number; items: ConversationItem[] }>()
  const unknownOlderItems: ConversationItem[] = []

  for (const item of conversations.value) {
    const updatedAt = parseConversationTimestamp(item.updated_at)
    if (Number.isNaN(updatedAt)) {
      unknownOlderItems.push(item)
      continue
    }

    const date = new Date(updatedAt)
    const itemDayStart = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
    const dayDiff = Math.floor((todayStart - itemDayStart) / MS_PER_DAY)

    if (dayDiff <= 0) {
      todayItems.push(item)
    } else if (dayDiff <= 30) {
      within30DaysItems.push(item)
    } else {
      const month = date.getMonth() + 1
      const year = date.getFullYear()
      const key = `${year}-${String(month).padStart(2, '0')}`
      const label = `${year}年${month}月`
      const existing = olderByMonth.get(key)
      if (existing) {
        existing.items.push(item)
      } else {
        olderByMonth.set(key, {
          label,
          sortKey: year * 100 + month,
          items: [item],
        })
      }
    }
  }

  const monthGroups = Array.from(olderByMonth.entries())
    .sort((a, b) => b[1].sortKey - a[1].sortKey)
    .map(([key, group]) => ({ key: `month-${key}`, label: group.label, items: group.items }))

  if (unknownOlderItems.length > 0) {
    monthGroups.push({ key: 'month-older', label: '更早', items: unknownOlderItems })
  }

  return [
    { key: 'today', label: '今天', items: todayItems },
    { key: 'within-30-days', label: '30天内', items: within30DaysItems },
    ...monthGroups,
  ].filter((group) => group.items.length > 0)
})

const loadConversations = async () => {
  try {
    await chatStore.loadConversations()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || '会话列表加载失败')
  }
}

const onNavSelect = async (index: string) => {
  if (index === '/chat') {
    chatStore.startNewConversation()
    await router.push({ path: '/chat', query: {} })
    return
  }
  await router.push(index)
}

const openConversation = async (conversationId: number) => {
  chatStore.setActiveConversation(conversationId)
  await router.push({ path: '/chat', query: { c: String(conversationId) } })
}

const renameConversation = async (item: ConversationItem) => {
  try {
    const result = await ElMessageBox.prompt('请输入新的会话标题', '重命名会话', {
      inputValue: item.title,
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    const title = result.value.trim()
    if (!title) return
    const res = await api.patch(`/interactions/conversations/${item.id}`, { title })
    if (res.data?.updated) {
      ElMessage.success('已重命名')
      await loadConversations()
    }
  } catch {
    // ignore cancel
  }
}

const deleteConversation = async (item: ConversationItem) => {
  try {
    await ElMessageBox.confirm(`确认删除会话「${item.title}」？`, '删除会话', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    const res = await api.delete(`/interactions/conversations/${item.id}`)
    if (res.data?.deleted) {
      if (activeConversationId.value === item.id) {
        chatStore.startNewConversation()
      }
      ElMessage.success('会话已删除')
      await loadConversations()
    }
  } catch {
    // ignore cancel
  }
}

const onConversationCommand = async (command: string, item: ConversationItem) => {
  if (command === 'rename') {
    await renameConversation(item)
  } else if (command === 'delete') {
    await deleteConversation(item)
  }
}

const logout = async () => {
  authStore.clear()
  ElMessage.success('已退出登录')
  await router.push('/login')
}

const openSettings = () => {
  if (!isAdmin.value) {
    ElMessage.warning('仅管理员可访问系统设置')
    return
  }
  void router.push('/model-settings')
}

const openLearningProfile = () => {
  profileDisplayName.value = userName.value || ''
  profileAvatarUrl.value = userAvatarUrl.value || ''
  profileDialogVisible.value = true
}

const saveLearningProfile = async () => {
  try {
    profileSaving.value = true
    const res = await api.patch('/auth/me', { display_name: profileDisplayName.value.trim() })
    userName.value = res.data?.display_name || userName.value
    userAvatarUrl.value = res.data?.avatar_url || userAvatarUrl.value
    profileAvatarUrl.value = userAvatarUrl.value
    profileDialogVisible.value = false
    ElMessage.success('个人中心已更新')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || '保存失败')
  } finally {
    profileSaving.value = false
  }
}

const regenerateAvatar = async () => {
  try {
    avatarRegenerating.value = true
    const res = await api.post('/auth/me/avatar/regenerate')
    userAvatarUrl.value = res.data?.avatar_url || userAvatarUrl.value
    profileAvatarUrl.value = userAvatarUrl.value
    ElMessage.success('头像已重新生成')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || '头像生成失败')
  } finally {
    avatarRegenerating.value = false
  }
}

const loadCurrentUser = async () => {
  try {
    const res = await api.get('/auth/me')
    userName.value = res.data.display_name || '当前用户'
    userEmail.value = res.data.email || ''
    userAvatarUrl.value = res.data.avatar_url || ''
    isAdmin.value = !!res.data.is_admin
  } catch {
    userName.value = '当前用户'
    userEmail.value = ''
    userAvatarUrl.value = ''
    isAdmin.value = false
  }
}

onMounted(() => {
  void loadCurrentUser()
  void loadConversations()
})
</script>

<template>
  <el-container class="shell-container">
    <el-aside width="250px" class="shell-aside">
      <div class="brand brand--with-logo">
        <img :src="yanzhouLogo" alt="言舟 logo" class="brand-logo" />
      </div>
      <div class="shell-nav">
        <el-menu :default-active="activePath" class="side-menu" @select="onNavSelect">
          <el-menu-item v-for="item in navItems" :key="item.to" :index="item.to">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </el-menu-item>
        </el-menu>

        <div class="history-divider" />
        <div class="history-root-item">
          <el-icon class="history-root-icon"><Clock /></el-icon>
          <span>历史会话</span>
        </div>
        <el-scrollbar class="conversation-nav-scroll conversation-nav-scroll--inline">
          <div v-if="groupedConversations.length > 0" class="conversation-groups">
            <div
              v-for="group in groupedConversations"
              :key="group.key"
              class="conversation-group"
            >
              <div class="conversation-group-title">{{ group.label }}</div>
              <div
                v-for="item in group.items"
                :key="item.id"
                class="conversation-nav-item conversation-nav-item--nested"
                :class="{ active: item.id === activeConversationId }"
                @click="openConversation(item.id)"
              >
                <span class="conversation-nav-title">{{ item.title }}</span>
                <el-dropdown
                  trigger="click"
                  @command="(cmd: string) => onConversationCommand(cmd, item)"
                  @click.stop
                >
                  <el-button text class="conversation-nav-more" @click.stop>
                    <el-icon><MoreFilled /></el-icon>
                  </el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="rename">重命名</el-dropdown-item>
                      <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </div>
          </div>
        </el-scrollbar>
      </div>

      <div class="shell-bottom">
        <el-menu :default-active="activePath" class="side-menu side-menu--admin" router>
          <el-menu-item v-for="item in adminItems" :key="item.to" :index="item.to">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </el-menu-item>
        </el-menu>

        <div class="user-panel">
          <el-avatar :src="userAvatarUrl || undefined" :icon="UserFilled" size="small" />
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
                <el-dropdown-item @click="openLearningProfile">
                  <el-icon><CollectionTag /></el-icon>
                  <span>个人中心</span>
                </el-dropdown-item>
                <el-dropdown-item v-if="isAdmin" @click="openSettings">
                  <el-icon><Setting /></el-icon>
                  <span>系统设置</span>
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

  <el-dialog v-model="profileDialogVisible" title="个人中心" width="420px">
    <div class="profile-dialog">
      <div class="profile-avatar-row">
        <el-avatar :src="profileAvatarUrl || undefined" :icon="UserFilled" :size="72" />
        <el-button :loading="avatarRegenerating" @click="regenerateAvatar">重新生成头像</el-button>
      </div>
      <el-form label-position="top">
        <el-form-item label="昵称">
          <el-input v-model="profileDisplayName" placeholder="请输入昵称" maxlength="120" />
        </el-form-item>
      </el-form>
    </div>
    <template #footer>
      <el-button @click="profileDialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="profileSaving" @click="saveLearningProfile">保存</el-button>
    </template>
  </el-dialog>
</template>
