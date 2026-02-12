<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { CloseBold, Top } from '@element-plus/icons-vue'
import { storeToRefs } from 'pinia'

import api, { API_BASE_URL } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useChatStore } from '../stores/chat'
import { renderMarkdownToHtml } from '../utils/markdownRender'

type CitationItem = {
  chunk_id: number
  chunk_index?: number
  preview: string
  relevance_score?: number
  document_id?: number
  document_filename?: string
  knowledge_base_id?: number
  knowledge_base_name?: string
}

type InteractionItem = {
  id: number
  conversation_id?: number
  question: string
  answer: string
  trace_id: string
  citations?: CitationItem[]
  created_at: string
}

const sending = ref(false)
const question = ref('')
const useMemoryStream = ref(true)
const history = ref<InteractionItem[]>([])
const streamController = ref<AbortController | null>(null)
const abortRequested = ref(false)
const authStore = useAuthStore()
const chatStore = useChatStore()
const router = useRouter()
const { activeConversationId } = storeToRefs(chatStore)
const loadingMessages = ref(false)
const dialogViewportRef = ref<HTMLElement | null>(null)
const isEmptyState = computed(() => history.value.length === 0)

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

const loadMessagesByConversationId = async (conversationId: number) => {
  loadingMessages.value = true
  try {
    const res = await api.get(`/interactions/conversations/${conversationId}/messages?limit=200`)
    history.value = res.data
    await scrollToBottom()
  } catch (e: any) {
    history.value = []
    ElMessage.error(e.response?.data?.detail || e.message || '会话消息加载失败')
  } finally {
    loadingMessages.value = false
  }
}

const MEMORY_SWITCH_STORAGE_KEY = 'chat.useMemoryStream'
const savedMemorySwitch = window.localStorage.getItem(MEMORY_SWITCH_STORAGE_KEY)
if (savedMemorySwitch === '0') {
  useMemoryStream.value = false
}

watch(useMemoryStream, (enabled) => {
  window.localStorage.setItem(MEMORY_SWITCH_STORAGE_KEY, enabled ? '1' : '0')
})

const send = async () => {
  const content = question.value.trim()
  if (!content || sending.value) return
  if (content.length < 2) {
    ElMessage.warning('问题至少输入 2 个字符')
    return
  }

  sending.value = true
  let streamCompleted = false
  let streamHasOutput = false
  let currentId = 0
  let resolvedConversationId = activeConversationId.value
  try {
    currentId = Number(new Date().getTime())
    abortRequested.value = false
    const controller = new AbortController()
    streamController.value = controller
    history.value.push({
      id: currentId,
      conversation_id: resolvedConversationId || undefined,
      question: content,
      answer: '',
      trace_id: '',
      citations: [],
      created_at: new Date().toISOString(),
    })
    question.value = ''

    const response = await fetch(`${API_BASE_URL}/query/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${authStore.token}`,
      },
      signal: controller.signal,
      body: JSON.stringify({
        question: content,
        conversation_id: activeConversationId.value || undefined,
        use_memory_stream: useMemoryStream.value,
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
          if (Array.isArray(payload.citations)) {
            target.citations = payload.citations
          }
          if (typeof payload.conversation_id === 'number') {
            resolvedConversationId = payload.conversation_id
            chatStore.setActiveConversation(payload.conversation_id)
            target.conversation_id = payload.conversation_id
          }
        } else if (payload.type === 'chunk') {
          streamHasOutput = true
          target.answer += payload.content || ''
        } else if (payload.type === 'done') {
          streamCompleted = true
          target.trace_id = payload.trace_id || target.trace_id
          if (Array.isArray(payload.citations)) {
            target.citations = payload.citations
          }
          if (typeof payload.conversation_id === 'number') {
            resolvedConversationId = payload.conversation_id
            chatStore.setActiveConversation(payload.conversation_id)
            target.conversation_id = payload.conversation_id
          }
          await chatStore.loadConversations()
          await scrollToBottom()
        } else if (payload.type === 'error') {
          throw new Error(payload.message || '流式响应异常')
        }
      }
    }
  } catch (e: any) {
    if (abortRequested.value || e?.name === 'AbortError') {
      return
    }
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
    streamController.value = null
    abortRequested.value = false
    if (resolvedConversationId && !activeConversationId.value) {
      chatStore.setActiveConversation(resolvedConversationId)
    }
    void chatStore.loadConversations()
  }
}

const stopReply = () => {
  if (!sending.value || !streamController.value) return
  abortRequested.value = true
  streamController.value.abort()
}

const onSendButtonClick = () => {
  if (sending.value) {
    stopReply()
    return
  }
  void send()
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

const openCitation = async (item: CitationItem) => {
  if (!item.document_id) return
  await router.push({
    path: '/knowledge',
    query: {
      docId: String(item.document_id),
      baseId: item.knowledge_base_id ? String(item.knowledge_base_id) : undefined,
      chunkId: item.chunk_id ? String(item.chunk_id) : undefined,
    },
  })
}

const activeConversationIdRef = computed(() => activeConversationId.value)

watch(
  activeConversationIdRef,
  async (conversationId) => {
    // Keep in-flight streamed message stable; avoid replacing local optimistic history.
    if (sending.value) {
      return
    }
    if (!conversationId) {
      history.value = []
      question.value = ''
      return
    }
    await loadMessagesByConversationId(conversationId)
  },
  { immediate: true },
)

watch(loadingMessages, async (loading) => {
  if (!loading) {
    await scrollToBottom()
  }
})
</script>

<template>
  <div class="chat-layout">
    <div class="chat-col chat-content">
      <el-card shadow="never" class="chat-card chat-card--fill chat-content-card">
        <div class="chat-main-panel" :class="{ 'chat-main-panel--empty': isEmptyState }">
          <div v-if="!isEmptyState" class="dialog-scroll" :ref="setDialogViewportRef">
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
              <div v-if="item.citations && item.citations.length > 0" class="message-row assistant">
                <div class="avatar avatar--ghost" />
                <div class="bubble-citations">
                  <div class="bubble-citations-title">参考资料</div>
                  <button
                    v-for="citation in item.citations"
                    :key="`${item.id}-citation-${citation.chunk_id}`"
                    class="bubble-citation-link"
                    type="button"
                    @click="openCitation(citation)"
                  >
                    <span class="bubble-citation-name">{{ citation.document_filename || `文档 #${citation.document_id || '-'}` }}</span>
                    <span class="bubble-citation-preview">{{ citation.preview }}</span>
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div v-if="isEmptyState" class="chat-empty-hero">
            <div class="chat-empty-title">
              <span>Hi! 👋 我是你的语言学习助手</span>
            </div>
          </div>

          <div class="chat-composer" :class="{ 'chat-composer--empty': isEmptyState }">
            <div class="composer-shell">
              <el-input
                v-model="question"
                class="chat-input"
                type="textarea"
                :autosize="{ minRows: 3, maxRows: 8 }"
                placeholder="输入消息（Enter 发送，Shift+Enter 换行）"
                @keydown="onKeydown"
              />
              <div class="composer-controls">
                <el-button
                  size="small"
                  class="memory-toggle-btn"
                  :type="useMemoryStream ? 'primary' : 'default'"
                  plain
                  @click="useMemoryStream = !useMemoryStream"
                >
                  记忆流
                </el-button>
              </div>
              <el-button
                class="send-icon-btn"
                :type="sending ? 'danger' : 'primary'"
                :icon="sending ? CloseBold : Top"
                circle
                @click="onSendButtonClick"
              />
            </div>
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>
