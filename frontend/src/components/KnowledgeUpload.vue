<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'

import api from '../api/client'

type KnowledgeBaseItem = {
  id: number
  name: string
  scope?: 'private' | 'public'
  can_manage?: boolean
  is_enabled: boolean
  document_count: number
  chunk_count: number
  created_at: string
  updated_at: string
}

type KnowledgeDocItem = {
  id: number
  knowledge_base_id: number
  filename: string
  content_type: string
  file_size?: number
  deleted_at?: string | null
  status: string
  progress: number
  total_chunks: number
  processed_chunks: number
  chunk_count: number
  error_message?: string | null
  created_at: string
}

const loadingBases = ref(false)
const loadingDocs = ref(false)
const uploading = ref(false)
const isAdmin = ref(false)
const includeDeleted = ref(false)
const bases = ref<KnowledgeBaseItem[]>([])
const docs = ref<KnowledgeDocItem[]>([])
const selectedBaseId = ref<number | null>(null)
const highlightedDocId = ref<number | null>(null)
const route = useRoute()
let pollTimer: number | null = null

const processingStatuses = new Set(['queued', 'slicing', 'embedding'])
const hasProcessingDocs = computed(() => docs.value.some((d) => processingStatuses.has(d.status)))
const selectedBaseCanManage = computed(() => {
  const base = bases.value.find((item) => item.id === selectedBaseId.value)
  return base ? base.can_manage !== false : false
})
const privateBases = computed(() => bases.value.filter((item) => (item.scope || 'private') === 'private'))
const publicBases = computed(() => bases.value.filter((item) => item.scope === 'public'))

const stopPolling = () => {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

const startPolling = () => {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    if (!selectedBaseId.value) return
    await loadDocs(selectedBaseId.value)
    if (!hasProcessingDocs.value) {
      stopPolling()
    }
  }, 1200)
}

const loadBases = async () => {
  loadingBases.value = true
  try {
    const res = await api.get('/knowledge/bases')
    bases.value = res.data
    if (!selectedBaseId.value && bases.value.length > 0) {
      selectedBaseId.value = bases.value[0].id
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || '知识库列表加载失败')
  } finally {
    loadingBases.value = false
  }
}

const loadDocs = async (baseId: number) => {
  loadingDocs.value = true
  try {
    const res = await api.get(`/knowledge/docs?knowledge_base_id=${baseId}&include_deleted=${includeDeleted.value}`)
    docs.value = res.data
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || '文档列表加载失败')
  } finally {
    loadingDocs.value = false
  }
}

const createBase = async (scope: 'private' | 'public' = 'private') => {
  try {
    const result = await ElMessageBox.prompt('请输入知识库名称', '新建知识库', {
      confirmButtonText: '创建',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：法语语法 / 旅游会话',
    })
    const name = result.value.trim()
    if (!name) return
    await api.post('/knowledge/bases', { name, scope, is_enabled: true })
    await loadBases()
    if (bases.value.length > 0) {
      selectedBaseId.value = bases.value[0].id
      await loadDocs(selectedBaseId.value)
    }
    ElMessage.success('知识库已创建')
  } catch {
    // ignore cancel
  }
}

const loadCurrentUser = async () => {
  try {
    const res = await api.get('/auth/me')
    isAdmin.value = !!res.data?.is_admin
  } catch {
    isAdmin.value = false
  }
}

const toggleBase = async (base: KnowledgeBaseItem, enabled: boolean) => {
  try {
    await api.patch(`/knowledge/bases/${base.id}`, { is_enabled: enabled })
    base.is_enabled = enabled
    ElMessage.success(enabled ? '已启用' : '已停用')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || '更新失败')
    base.is_enabled = !enabled
  }
}

const onBaseChange = async () => {
  if (!selectedBaseId.value) {
    docs.value = []
    return
  }
  await loadDocs(selectedBaseId.value)
  if (hasProcessingDocs.value) {
    startPolling()
  } else {
    stopPolling()
  }
}

const parseRouteInt = (value: unknown): number | null => {
  if (typeof value !== 'string') return null
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) ? parsed : null
}

const applyRouteSelection = async () => {
  const baseId = parseRouteInt(route.query.baseId)
  const docId = parseRouteInt(route.query.docId)
  highlightedDocId.value = docId
  if (baseId && bases.value.some((base) => base.id === baseId) && selectedBaseId.value !== baseId) {
    selectedBaseId.value = baseId
  }
  if (selectedBaseId.value) {
    await loadDocs(selectedBaseId.value)
  }
}

const docRowClassName = ({ row }: { row: KnowledgeDocItem }) =>
  highlightedDocId.value && row.id === highlightedDocId.value ? 'knowledge-doc-row--highlight' : ''

const parseFilenameFromDisposition = (value?: string): string | null => {
  if (!value) return null
  const match = /filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)\"?/i.exec(value)
  const encoded = match?.[1]
  const plain = match?.[2]
  if (encoded) {
    try {
      return decodeURIComponent(encoded)
    } catch {
      return encoded
    }
  }
  return plain || null
}

const downloadDoc = async (row: KnowledgeDocItem) => {
  try {
    const res = await api.get(`/knowledge/docs/${row.id}/download`, { responseType: 'blob' })
    const disposition = String(res.headers['content-disposition'] || '')
    const filename = parseFilenameFromDisposition(disposition) || row.filename || `document-${row.id}`
    const blob = new Blob([res.data], { type: row.content_type || 'application/octet-stream' })
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.URL.revokeObjectURL(url)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || '下载失败')
  }
}

const customUpload = async (options: UploadRequestOptions) => {
  if (!selectedBaseId.value) {
    ElMessage.warning('请先选择一个知识库')
    options.onError?.(new Error('missing knowledge base'))
    return
  }

  const formData = new FormData()
  formData.append('file', options.file)

  try {
    uploading.value = true
    const res = await api.post(`/knowledge/upload?knowledge_base_id=${selectedBaseId.value}`, formData)
    options.onSuccess?.(res.data)
    ElMessage.success('文档已提交处理')
    await loadBases()
    await loadDocs(selectedBaseId.value)
    startPolling()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || '上传失败')
    options.onError?.(e)
  } finally {
    uploading.value = false
  }
}

const formatStatus = (status: string) => {
  if (status === 'queued') return '排队中'
  if (status === 'slicing') return '切片中'
  if (status === 'embedding') return '向量化中'
  if (status === 'completed') return '已完成'
  if (status === 'failed') return '失败'
  return status
}

const formatFileSize = (size?: number) => {
  const value = Number(size || 0)
  if (!Number.isFinite(value) || value <= 0) return '-'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`
  return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

const formatDateTime = (value?: string) => {
  if (!value) return '-'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString('zh-CN', { hour12: false })
}

const deleteDoc = async (row: KnowledgeDocItem) => {
  try {
    await ElMessageBox.confirm(`确认删除文档「${row.filename}」？`, '删除文档', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await api.delete(`/knowledge/docs/${row.id}`)
    ElMessage.success('文档已删除')
    if (selectedBaseId.value) {
      await loadDocs(selectedBaseId.value)
      await loadBases()
    }
  } catch (e: any) {
    if (e === 'cancel' || e === 'close' || e?.message === 'cancel') return
    ElMessage.error(e.response?.data?.detail || e.message || '删除失败')
  }
}

const restoreDoc = async (row: KnowledgeDocItem) => {
  try {
    await api.post(`/knowledge/docs/${row.id}/restore`)
    ElMessage.success('文档已恢复')
    if (selectedBaseId.value) {
      await loadDocs(selectedBaseId.value)
      await loadBases()
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || '恢复失败')
  }
}

onMounted(async () => {
  await loadCurrentUser()
  await loadBases()
  await applyRouteSelection()
  if (hasProcessingDocs.value) {
    startPolling()
  }
})

watch(
  () => route.query,
  () => {
    void applyRouteSelection()
  },
)

watch(includeDeleted, async () => {
  if (selectedBaseId.value) {
    await loadDocs(selectedBaseId.value)
  }
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<template>
  <section class="knowledge-layout">
    <el-card shadow="never" class="knowledge-bases-card">
      <template #header>
        <div class="card-header-row">
          <span />
          <div class="row">
            <el-button size="small" @click="createBase('private')">新建私有</el-button>
            <el-button v-if="isAdmin" size="small" type="warning" plain @click="createBase('public')">新建公共</el-button>
            <el-button size="small" :loading="loadingBases" @click="loadBases">刷新</el-button>
          </div>
        </div>
      </template>

      <el-scrollbar class="knowledge-base-scroll">
        <div class="knowledge-base-group">
          <div class="knowledge-base-group-title">私有</div>
          <div v-if="privateBases.length === 0" class="knowledge-base-empty">暂无私有知识库</div>
          <div
            v-for="base in privateBases"
            :key="base.id"
            class="knowledge-base-item"
            :class="{ active: base.id === selectedBaseId }"
            @click="selectedBaseId = base.id; void onBaseChange()"
          >
            <div class="knowledge-base-main">
              <div class="knowledge-base-name">{{ base.name }}</div>
              <div class="knowledge-base-meta">文档 {{ base.document_count }} · 切片 {{ base.chunk_count }}</div>
            </div>
            <el-switch
              :model-value="base.is_enabled"
              :disabled="base.can_manage === false"
              @change="(val: string | number | boolean) => toggleBase(base, !!val)"
              @click.stop
            />
          </div>
        </div>

        <div class="knowledge-base-group knowledge-base-group--public">
          <div class="knowledge-base-group-title">公共</div>
          <div v-if="publicBases.length === 0" class="knowledge-base-empty">暂无公共知识库</div>
          <div
            v-for="base in publicBases"
            :key="base.id"
            class="knowledge-base-item"
            :class="{ active: base.id === selectedBaseId }"
            @click="selectedBaseId = base.id; void onBaseChange()"
          >
            <div class="knowledge-base-main">
              <div class="knowledge-base-name">{{ base.name }}</div>
              <div class="knowledge-base-meta">文档 {{ base.document_count }} · 切片 {{ base.chunk_count }}</div>
            </div>
            <el-switch
              :model-value="base.is_enabled"
              :disabled="base.can_manage === false"
              @change="(val: string | number | boolean) => toggleBase(base, !!val)"
              @click.stop
            />
          </div>
        </div>
      </el-scrollbar>
    </el-card>

    <el-card shadow="never" class="knowledge-docs-card">
      <template #header>
        <div class="card-header-row">
          <span>文档管理</span>
          <div class="row">
            <el-switch
              v-model="includeDeleted"
              active-text="显示已删除"
              :disabled="!selectedBaseCanManage"
            />
            <el-select v-model="selectedBaseId" size="small" style="width: 220px" @change="onBaseChange">
              <el-option v-for="base in bases" :key="base.id" :label="base.name" :value="base.id" />
            </el-select>
          </div>
        </div>
      </template>

      <el-upload
        drag
        :show-file-list="false"
        :http-request="customUpload"
        :disabled="uploading || !selectedBaseId || !selectedBaseCanManage"
        accept=".md,.markdown,.json,.txt,.pdf,.docx"
      >
        <div style="font-size: 16px; margin-bottom: 6px">上传文档到当前知识库</div>
        <div>支持 Markdown / JSON / TXT / PDF / DOCX</div>
      </el-upload>

      <el-table
        :data="docs"
        :row-class-name="docRowClassName"
        style="margin-top: 14px"
        v-loading="loadingDocs"
        size="small"
      >
        <el-table-column label="文档" min-width="180">
          <template #default="{ row }">
            <button
              type="button"
              class="doc-download-link"
              :disabled="!!row.deleted_at"
              @click="downloadDoc(row)"
            >
              {{ row.filename }}
            </button>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.deleted_at" type="info" size="small">已删除</el-tag>
            <span v-else>{{ formatStatus(row.status) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="110">
          <template #default="{ row }">{{ formatFileSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="上传时间" min-width="170">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="进度" min-width="170">
          <template #default="{ row }">
            <el-progress :percentage="row.progress || 0" :stroke-width="10" />
          </template>
        </el-table-column>
        <el-table-column label="切片" width="130">
          <template #default="{ row }">{{ row.processed_chunks }}/{{ row.total_chunks }}</template>
        </el-table-column>
        <el-table-column label="总切片" width="90">
          <template #default="{ row }">{{ row.chunk_count }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button
              :type="row.deleted_at ? 'primary' : 'danger'"
              text
              :disabled="!selectedBaseCanManage"
              @click="row.deleted_at ? restoreDoc(row) : deleteDoc(row)"
            >
              {{ row.deleted_at ? '恢复' : '删除' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </section>
</template>
