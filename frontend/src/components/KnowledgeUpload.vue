<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'

import api from '../api/client'

type KnowledgeBaseItem = {
  id: number
  name: string
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
const bases = ref<KnowledgeBaseItem[]>([])
const docs = ref<KnowledgeDocItem[]>([])
const selectedBaseId = ref<number | null>(null)
let pollTimer: number | null = null

const processingStatuses = new Set(['queued', 'slicing', 'embedding'])
const hasProcessingDocs = computed(() => docs.value.some((d) => processingStatuses.has(d.status)))

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
    const res = await api.get(`/knowledge/docs?knowledge_base_id=${baseId}`)
    docs.value = res.data
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || '文档列表加载失败')
  } finally {
    loadingDocs.value = false
  }
}

const createBase = async () => {
  try {
    const result = await ElMessageBox.prompt('请输入知识库名称', '新建知识库', {
      confirmButtonText: '创建',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：法语语法 / 旅游会话',
    })
    const name = result.value.trim()
    if (!name) return
    await api.post('/knowledge/bases', { name, is_enabled: true })
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

onMounted(async () => {
  await loadBases()
  if (selectedBaseId.value) {
    await loadDocs(selectedBaseId.value)
  }
  if (hasProcessingDocs.value) {
    startPolling()
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
          <span>知识库</span>
          <div class="row">
            <el-button size="small" @click="createBase">新建</el-button>
            <el-button size="small" :loading="loadingBases" @click="loadBases">刷新</el-button>
          </div>
        </div>
      </template>

      <el-scrollbar class="knowledge-base-scroll">
        <div
          v-for="base in bases"
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
            @change="(val: string | number | boolean) => toggleBase(base, !!val)"
            @click.stop
          />
        </div>
      </el-scrollbar>
    </el-card>

    <el-card shadow="never" class="knowledge-docs-card">
      <template #header>
        <div class="card-header-row">
          <span>文档管理</span>
          <el-select v-model="selectedBaseId" size="small" style="width: 220px" @change="onBaseChange">
            <el-option v-for="base in bases" :key="base.id" :label="base.name" :value="base.id" />
          </el-select>
        </div>
      </template>

      <el-upload
        drag
        :show-file-list="false"
        :http-request="customUpload"
        :disabled="uploading || !selectedBaseId"
        accept=".md,.markdown,.json,.txt,.pdf,.docx"
      >
        <div style="font-size: 16px; margin-bottom: 6px">上传文档到当前知识库</div>
        <div>支持 Markdown / JSON / TXT / PDF / DOCX</div>
      </el-upload>

      <el-table :data="docs" style="margin-top: 14px" v-loading="loadingDocs" size="small">
        <el-table-column prop="filename" label="文档" min-width="180" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            {{ formatStatus(row.status) }}
          </template>
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
      </el-table>
    </el-card>
  </section>
</template>
