<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Top, Expand, Fold, MoreFilled } from '@element-plus/icons-vue'

import api, { API_BASE_URL } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { renderMarkdownToHtml } from '../utils/markdownRender'

type InteractionItem = {
  id: number
  conversation_id?: number
  question: string
  answer: string
  trace_id: string
  created_at: string
}

type ConversationItem = {
  id: number
  title: string
  created_at: string
  updated_at: string
}

const loading = ref(false)
const sending = ref(false)
const question = ref('')
const history = ref<InteractionItem[]>([])
const conversations = ref<ConversationItem[]>([])
const authStore = useAuthStore()
const activeConversationId = ref<number | null>(null)
const sidebarCollapsed = ref(false)
const dialogViewportRef = ref<HTMLElement | null>(null)

const setDialogViewportRef = (el: Element | null) => {
  dialogViewportRef.value = el as HTMLElement | null
}

const scrollToBottom = async (smooth = false) => {
  await nextTick()
  const container = dialogViewportRef.value
  if (!container) return
  container.scrollTo({
    top: container.scrollHeight,
    behavior: smooth ? 'smooth' : 'auto',
  })
}

const loadConversations = async () => {
  loading.value = true
  try {
    const res = await api.get('/interactions/conversations?limit=50')
    conversations.value = res.data
    if (!activeConversationId.value && conversations.value.length > 0) {
      await switchConversation(conversations.value[0].id)
    }
  } catch (e: any) {
    conversations.value = []
    ElMessage.error(e.response?.data?.detail || e.message || '会话列表加载失败')
  } finally {
    loading.value = false
  }
}

const startNewConversation = () => {
  activeConversationId.value = null
  history.value = []
  question.value = ''
}

const switchConversation = async (conversationId: number) => {
  activeConversationId.value = conversationId
  loading.value = true
  try {
    const res = await api.get(`/interactions/conversations/${conversationId}/messages?limit=200`)
    history.value = res.data
    await scrollToBottom()
  } catch (e: any) {
    history.value = []
    ElMessage.error(e.response?.data?.detail || e.message || '会话消息加载失败')
  } finally {
    loading.value = false
  }
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
        activeConversationId.value = null
        history.value = []
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

const send = async () => {
  const content = question.value.trim()
  if (!content || sending.value) return
  if (content.length < 2) {
    ElMessage.warning('问题至少输入 2 个字符')
    return
  }

  question.value = ''
  sending.value = true
  let streamCompleted = false
  let streamHasOutput = false
  let currentId = 0
  let resolvedConversationId = activeConversationId.value
  try {
    currentId = Number(new Date().getTime())
    history.value.push({
      id: currentId,
      conversation_id: resolvedConversationId || undefined,
      question: content,
      answer: '',
      trace_id: '',
      created_at: new Date().toISOString(),
    })
    await scrollToBottom(true)

    const response = await fetch(`${API_BASE_URL}/query/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${authStore.token}`,
      },
      body: JSON.stringify({
        question: content,
        conversation_id: activeConversationId.value,
      }),
    })
    if (!response.ok || !response.body) {
      throw new Error(`流式请求失败: ${response.status}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    let finished = false

    while (!finished) {
      const result = await reader.read()
      finished = result.done
      buffer += decoder.decode(result.value || new Uint8Array(), { stream: true })

      const events = buffer.split('\n\n')
      buffer = events.pop() || ''

      for (const eventBlock of events) {
        const dataLine = eventBlock
          .split('\n')
          .map((line) => line.trim())
          .find((line) => line.startsWith('data: '))
        if (!dataLine) continue

        let payload: any
        try {
          payload = JSON.parse(dataLine.slice(6))
        } catch {
          continue
        }

        const target = history.value.find((item) => item.id === currentId)
        if (!target) continue

        if (payload.type === 'start') {
          if (typeof payload.conversation_id === 'number') {
            resolvedConversationId = payload.conversation_id
            activeConversationId.value = payload.conversation_id
            target.conversation_id = payload.conversation_id
          }
        } else if (payload.type === 'chunk') {
          streamHasOutput = true
          target.answer += payload.content || ''
          await scrollToBottom()
        } else if (payload.type === 'done') {
          streamCompleted = true
          target.trace_id = payload.trace_id || target.trace_id
          if (typeof payload.conversation_id === 'number') {
            resolvedConversationId = payload.conversation_id
            activeConversationId.value = payload.conversation_id
            target.conversation_id = payload.conversation_id
          }
          await loadConversations()
          await scrollToBottom()
        } else if (payload.type === 'error') {
          throw new Error(payload.message || '流式响应异常')
        }
      }
    }
  } catch (e: any) {
    // Some providers close SSE sockets abruptly after final token.
    // If we already rendered content or got done signal, treat it as successful completion.
    if (streamCompleted || streamHasOutput) {
      return
    }
    const target = history.value.find((item) => item.id === currentId)
    if (target && target.answer.trim()) {
      return
    }
    ElMessage.error(e.response?.data?.detail || e.message || '发送失败')
  } finally {
    sending.value = false
    if (resolvedConversationId && !activeConversationId.value) {
      activeConversationId.value = resolvedConversationId
    }
    void loadConversations()
  }
}

const onKeydown = (event: KeyboardEvent) => {
  if ((event as KeyboardEvent).isComposing) {
    return
  }
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void send()
  }
}

onMounted(() => {
  void loadConversations()
})
</script>

<template>
  <div class="chat-layout" :class="{ 'chat-layout--sidebar-collapsed': sidebarCollapsed }">
    <el-button
      v-if="sidebarCollapsed"
      class="sidebar-float-btn"
      type="primary"
      :icon="Expand"
      circle
      @click="sidebarCollapsed = false"
    />

    <div v-if="!sidebarCollapsed" class="chat-col chat-sidebar">
      <div class="chat-drawer-panel">
        <div class="card-header-row chat-drawer-header">
          <el-button size="small" text :icon="Fold" @click="sidebarCollapsed = true">
            收起
          </el-button>
        </div>

        <div class="new-chat-row">
          <el-button type="primary" class="new-chat-btn" @click="startNewConversation">
            <el-icon><Plus /></el-icon>
            <span>开启新会话</span>
          </el-button>
        </div>

        <el-scrollbar class="history-scroll">
          <button
            v-for="item in conversations"
            :key="item.id"
            type="button"
            class="history-item"
            :class="{ active: item.id === activeConversationId }"
            @click="switchConversation(item.id)"
          >
            <div class="history-item-row">
              <div class="history-item-main">
                <div class="history-question">{{ item.title }}</div>
                <div class="history-meta">{{ item.updated_at }}</div>
              </div>
              <el-dropdown
                trigger="click"
                @command="(cmd: string) => onConversationCommand(cmd, item)"
                @click.stop
              >
                <el-button text size="small" class="history-more-btn" @click.stop>
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
          </button>
        </el-scrollbar>
      </div>
    </div>

    <div class="chat-col chat-content">
      <el-card shadow="never" class="chat-card chat-card--fill chat-content-card">
        <div class="chat-main-panel">
          <div class="dialog-scroll" :ref="setDialogViewportRef">
            <div
              v-for="item in history"
              :key="`chat-${item.id}`"
              class="dialog-pair"
            >
              <div class="message-row user">
                <div class="bubble user">{{ item.question }}</div>
                <el-avatar size="small" class="avatar user">我</el-avatar>
              </div>
              <div class="message-row assistant">
                <el-avatar size="small" class="avatar assistant">AI</el-avatar>
                <div class="bubble assistant">
                  <template v-if="sending && !item.answer && item.id === history[history.length - 1]?.id">
                    <span class="typing-dots">
                      <i />
                      <i />
                      <i />
                    </span>
                  </template>
                  <template v-else>
                    <div class="markdown-body" v-html="renderMarkdownToHtml(item.answer || '')" />
                  </template>
                </div>
              </div>
            </div>
          </div>
          <div class="chat-composer">
            <div class="composer-shell">
              <el-input
                v-model="question"
                class="chat-input"
                type="textarea"
                :autosize="{ minRows: 3, maxRows: 8 }"
                placeholder="输入消息（Enter 发送，Shift+Enter 换行）"
                @keydown="onKeydown"
              />
              <el-button
                class="send-icon-btn"
                type="primary"
                :icon="Top"
                circle
                :loading="sending"
                @click="send"
              />
            </div>
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>
