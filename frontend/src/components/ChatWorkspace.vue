<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { CaretBottom, CloseBold, Top } from '@element-plus/icons-vue'
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
  source?: string
  source_name?: string
  url?: string
}

type InteractionItem = {
  id: number
  conversation_id?: number
  question: string
  answer: string
  trace_id: string
  citations?: CitationItem[]
  pending_status?: string
  web_count?: number
  created_at: string
}

type ChatModelOption = {
  id: number
  provider_id: number
  provider_name: string
  model_name: string
  display_name: string
  model_type: 'language' | 'vision_language' | 'reasoning'
  description?: string
  tags: string[]
}

type HomeDashboard = {
  streak_days: number
  week_activity_days: number
  week_interactions: number
  week_quizzes: number
  active_language?: {
    language_code: string
    language_label: string
  } | null
  current_level?: {
    id: number
    title: string
    level_index: number
    completion_rate: number
  } | null
  plan_progress: {
    total_classes: number
    completed_classes: number
    completion_rate: number
    completed_recent: number
  }
  milestones: {
    total_conversations: number
    total_interactions: number
  }
}

const sending = ref(false)
const question = ref('')
const useMemoryStream = ref(true)
const useWebSearch = ref(false)
const history = ref<InteractionItem[]>([])
const streamController = ref<AbortController | null>(null)
const abortRequested = ref(false)
const authStore = useAuthStore()
const chatStore = useChatStore()
const router = useRouter()
const { activeConversationId } = storeToRefs(chatStore)
const loadingMessages = ref(false)
const loadingModels = ref(false)
const dialogViewportRef = ref<HTMLElement | null>(null)
const isEmptyState = computed(() => history.value.length === 0)
const citationDrawerVisible = ref(false)
const citationDrawerItems = ref<CitationItem[]>([])
const robotEyeX = ref(0)
const robotEyeY = ref(0)
const robotBlink = ref(false)
const robotClickPulse = ref(false)
const chatModelOptions = ref<ChatModelOption[]>([])
const selectedChatModelId = ref<number | null>(null)
const modelPickerVisible = ref(false)
const selectedChatModel = computed(() =>
  chatModelOptions.value.find((item) => item.id === selectedChatModelId.value) || null,
)
const homeDashboard = ref<HomeDashboard | null>(null)
const loadingHomeDashboard = ref(false)

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
const WEB_SEARCH_STORAGE_KEY = 'chat.useWebSearch'
const CHAT_MODEL_STORAGE_KEY = 'chat.selectedModelId'
const savedMemorySwitch = window.localStorage.getItem(MEMORY_SWITCH_STORAGE_KEY)
if (savedMemorySwitch === '0') {
  useMemoryStream.value = false
}
const savedWebSearch = window.localStorage.getItem(WEB_SEARCH_STORAGE_KEY)
if (savedWebSearch === '1') {
  useWebSearch.value = true
}
const savedModelId = window.localStorage.getItem(CHAT_MODEL_STORAGE_KEY)
if (savedModelId) {
  const parsed = Number.parseInt(savedModelId, 10)
  if (Number.isFinite(parsed) && parsed > 0) {
    selectedChatModelId.value = parsed
  }
}

watch(useMemoryStream, (enabled) => {
  window.localStorage.setItem(MEMORY_SWITCH_STORAGE_KEY, enabled ? '1' : '0')
})
watch(useWebSearch, (enabled) => {
  window.localStorage.setItem(WEB_SEARCH_STORAGE_KEY, enabled ? '1' : '0')
})

watch(selectedChatModelId, (value) => {
  if (!value) {
    window.localStorage.removeItem(CHAT_MODEL_STORAGE_KEY)
    return
  }
  window.localStorage.setItem(CHAT_MODEL_STORAGE_KEY, String(value))
})

const modelTypeText = (value?: string) => {
  if (value === 'language') return '语言模型'
  if (value === 'vision_language') return '视觉语言模型'
  if (value === 'reasoning') return '推理模型'
  return '模型'
}

const loadChatModels = async () => {
  loadingModels.value = true
  try {
    const res = await api.get('/model-settings/chat-models')
    chatModelOptions.value = Array.isArray(res.data) ? res.data : []
    if (
      selectedChatModelId.value &&
      !chatModelOptions.value.some((item) => item.id === selectedChatModelId.value)
    ) {
      selectedChatModelId.value = null
    }
    if (!selectedChatModelId.value && chatModelOptions.value.length > 0) {
      selectedChatModelId.value = chatModelOptions.value[0].id
    }
  } catch (e: any) {
    chatModelOptions.value = []
    selectedChatModelId.value = null
    ElMessage.error(e.response?.data?.detail || e.message || '模型列表加载失败')
  } finally {
    loadingModels.value = false
  }
}

const loadHomeDashboard = async () => {
  try {
    loadingHomeDashboard.value = true
    const res = await api.get('/interactions/home-dashboard')
    homeDashboard.value = res.data || null
  } catch {
    homeDashboard.value = null
  } finally {
    loadingHomeDashboard.value = false
  }
}

const selectChatModel = (modelId: number) => {
  selectedChatModelId.value = modelId
  modelPickerVisible.value = false
}

const randomizeRobotEyes = () => {
  robotEyeX.value = Math.round((Math.random() * 2 - 1) * 2)
  robotEyeY.value = Math.round((Math.random() * 2 - 1) * 2)
  if (Math.random() < 0.18) {
    robotBlink.value = true
    window.setTimeout(() => {
      robotBlink.value = false
    }, 140)
  }
}

const onRobotClick = () => {
  robotClickPulse.value = true
  randomizeRobotEyes()
  window.setTimeout(() => {
    robotClickPulse.value = false
  }, 260)
}

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
      pending_status: useWebSearch.value ? '正在联网搜索...' : '正在思考回答...',
      web_count: 0,
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
        use_web_search: useWebSearch.value,
        chat_model_id: selectedChatModelId.value || undefined,
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
          target.pending_status = ''
          target.answer += payload.content || ''
          randomizeRobotEyes()
        } else if (payload.type === 'status') {
          target.pending_status = payload.status || target.pending_status || ''
          if (typeof payload.web_count === 'number') {
            target.web_count = payload.web_count
          }
          randomizeRobotEyes()
        } else if (payload.type === 'done') {
          streamCompleted = true
          target.pending_status = ''
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
    void loadHomeDashboard()
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
  if (item.url) {
    window.open(item.url, '_blank', 'noopener,noreferrer')
    return
  }
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

const citationStats = (citations?: CitationItem[]) => {
  const list = citations || []
  const web = list.filter((item) => item.source === 'web').length
  return { web, kb: list.length - web }
}

const citationSummaryText = (citations?: CitationItem[]) => {
  const stats = citationStats(citations)
  const parts: string[] = []
  if (stats.web > 0) {
    parts.push(`网页 ${stats.web} 个`)
  }
  if (stats.kb > 0) {
    parts.push(`知识库 ${stats.kb} 条`)
  }
  return `参考资料：${parts.join('，')}`
}

const openCitationDrawer = (item: InteractionItem) => {
  citationDrawerItems.value = item.citations || []
  citationDrawerVisible.value = true
}

const drawerWebCitations = computed(() => citationDrawerItems.value.filter((item) => item.source === 'web'))
const drawerKbCitations = computed(() => citationDrawerItems.value.filter((item) => item.source !== 'web'))

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

onMounted(() => {
  void loadChatModels()
  void loadHomeDashboard()
})
</script>

<template>
  <div class="chat-layout" :class="{ 'has-citation-drawer': citationDrawerVisible }">
    <div class="chat-col chat-content">
      <el-card shadow="never" class="chat-card chat-card--fill chat-content-card">
        <div class="chat-main-panel" :class="{ 'chat-main-panel--empty': isEmptyState }">
          <div class="chat-head">
            <div class="chat-head-left">
              <el-popover
                v-model:visible="modelPickerVisible"
                trigger="click"
                placement="bottom-start"
                :width="420"
                popper-class="chat-model-popover"
              >
                <template #reference>
                  <button type="button" class="chat-model-trigger">
                    <span class="chat-model-trigger-title">{{ selectedChatModel?.display_name || '选择模型' }}</span>
                    <el-icon class="chat-model-trigger-icon"><CaretBottom /></el-icon>
                  </button>
                </template>
                <div class="chat-model-list" v-loading="loadingModels">
                  <button
                    v-for="item in chatModelOptions"
                    :key="item.id"
                    type="button"
                    class="chat-model-item"
                    :class="{ active: item.id === selectedChatModelId }"
                    @click="selectChatModel(item.id)"
                  >
                    <div class="chat-model-option">
                      <div class="chat-model-option-header">
                        <span class="chat-model-option-name">{{ item.display_name }}</span>
                        <el-tag size="small" type="info" effect="plain">{{ modelTypeText(item.model_type) }}</el-tag>
                      </div>
                      <div class="chat-model-option-meta">
                        <span class="chat-model-option-provider">{{ item.provider_name }}</span>
                        <span v-if="item.description" class="chat-model-option-desc">{{ item.description }}</span>
                      </div>
                      <div v-if="item.tags && item.tags.length > 0" class="chat-model-option-tags">
                        <el-tag v-for="tag in item.tags" :key="`${item.id}-${tag}`" size="small" effect="plain">{{ tag }}</el-tag>
                      </div>
                    </div>
                  </button>
                </div>
              </el-popover>
            </div>
            <div class="chat-head-right" />
          </div>
          <div v-if="!isEmptyState" class="dialog-scroll" :ref="setDialogViewportRef">
            <div
              v-for="item in history"
              :key="`chat-${item.id}`"
              class="dialog-pair"
            >
              <div class="message-row user">
                <div class="bubble user">{{ item.question }}</div>
              </div>
              <div class="message-row assistant">
                <button
                  type="button"
                  class="robot-avatar-btn"
                  :class="{
                    'is-thinking': sending && item.id === history[history.length - 1]?.id,
                    'is-blink': robotBlink,
                    'is-click': robotClickPulse,
                  }"
                  :style="{ '--eye-x': `${robotEyeX}px`, '--eye-y': `${robotEyeY}px` }"
                  @click="onRobotClick"
                >
                  <span class="robot-head">
                    <span class="robot-antenna" />
                    <span class="robot-face">
                      <span class="robot-eye robot-eye--left" />
                      <span class="robot-eye robot-eye--right" />
                      <span class="robot-mouth" />
                    </span>
                  </span>
                </button>
                <div class="bubble assistant">
                  <template v-if="sending && !item.answer && item.id === history[history.length - 1]?.id">
                    <span class="assistant-status-text">{{ item.pending_status || '正在思考回答...' }}</span>
                  </template>
                  <template v-else>
                    <div class="markdown-body" v-html="renderMarkdownToHtml(item.answer || '')" />
                  </template>
                </div>
              </div>
              <div v-if="item.citations && item.citations.length > 0" class="message-row assistant">
                <div class="avatar avatar--ghost" />
                <button class="bubble-citation-summary" type="button" @click="openCitationDrawer(item)">
                  {{ citationSummaryText(item.citations) }}
                </button>
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
                <el-button
                  size="small"
                  class="memory-toggle-btn"
                  :type="useWebSearch ? 'primary' : 'default'"
                  plain
                  @click="useWebSearch = !useWebSearch"
                >
                  联网搜索
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

          <div v-if="isEmptyState" class="chat-home-dashboard" v-loading="loadingHomeDashboard">
            <div class="chat-home-grid">
              <div class="chat-home-card">
                <div class="chat-home-card-label">连续学习</div>
                <div class="chat-home-card-value">{{ homeDashboard?.streak_days ?? 0 }} 天</div>
                <div class="chat-home-card-sub">本周活跃 {{ homeDashboard?.week_activity_days ?? 0 }} 天</div>
              </div>
              <div class="chat-home-card">
                <div class="chat-home-card-label">当前关卡</div>
                <div class="chat-home-card-value">Level {{ homeDashboard?.current_level?.level_index ?? '-' }}</div>
                <div class="chat-home-card-sub">{{ homeDashboard?.current_level?.title || '尚未开始计划' }}</div>
              </div>
              <div class="chat-home-card">
                <div class="chat-home-card-label">计划执行</div>
                <div class="chat-home-card-value">
                  {{ Math.round((homeDashboard?.plan_progress?.completion_rate || 0) * 100) }}%
                </div>
                <div class="chat-home-card-sub">
                  已完成 {{ homeDashboard?.plan_progress?.completed_classes ?? 0 }}/{{ homeDashboard?.plan_progress?.total_classes ?? 0 }} 个 class
                </div>
              </div>
              <div class="chat-home-card">
                <div class="chat-home-card-label">本周学习</div>
                <div class="chat-home-card-value">{{ homeDashboard?.week_interactions ?? 0 }} 次对话</div>
                <div class="chat-home-card-sub">{{ homeDashboard?.week_quizzes ?? 0 }} 次测验 · 新完成 {{ homeDashboard?.plan_progress?.completed_recent ?? 0 }} 课</div>
              </div>
            </div>
          </div>
        </div>
      </el-card>
    </div>

    <el-drawer
      v-model="citationDrawerVisible"
      direction="rtl"
      size="var(--citation-drawer-width)"
      :modal="false"
      :lock-scroll="false"
      title="参考资料详情"
      class="citation-drawer"
    >
      <div v-if="drawerWebCitations.length > 0" class="citation-drawer-section">
        <div class="citation-drawer-title">网页引用（{{ drawerWebCitations.length }}）</div>
        <button
          v-for="citation in drawerWebCitations"
          :key="`drawer-web-${citation.chunk_id}`"
          type="button"
          class="citation-drawer-item"
          @click="openCitation(citation)"
        >
          <div class="citation-drawer-item-title">{{ citation.document_filename || '联网搜索结果' }}</div>
          <div class="citation-drawer-item-meta">{{ citation.source_name || 'web' }}</div>
          <div class="citation-drawer-item-link">{{ citation.url || '-' }}</div>
          <div class="citation-drawer-item-preview">{{ citation.preview }}</div>
        </button>
      </div>

      <div v-if="drawerKbCitations.length > 0" class="citation-drawer-section">
        <div class="citation-drawer-title">知识库引用（{{ drawerKbCitations.length }}）</div>
        <button
          v-for="citation in drawerKbCitations"
          :key="`drawer-kb-${citation.chunk_id}`"
          type="button"
          class="citation-drawer-item"
          @click="openCitation(citation)"
        >
          <div class="citation-drawer-item-title">{{ citation.document_filename || `文档 #${citation.document_id || '-'}` }}</div>
          <div class="citation-drawer-item-meta">切片 {{ citation.chunk_index ?? '-' }}</div>
          <div class="citation-drawer-item-preview">{{ citation.preview }}</div>
        </button>
      </div>
      <div v-if="drawerWebCitations.length === 0 && drawerKbCitations.length === 0" class="citation-drawer-empty">暂无参考资料</div>
    </el-drawer>
  </div>
</template>
