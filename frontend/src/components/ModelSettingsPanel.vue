<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import api from '../api/client'

type ProviderItem = {
  id: number
  name: string
  base_url: string
  is_enabled: boolean
  has_api_key: boolean
}

type ModelItem = {
  id: number
  provider_id: number
  provider_name: string
  model_name: string
  display_name: string
  model_type: 'language' | 'vision_language' | 'reasoning' | 'embedding'
  description?: string
  tags: string[]
  is_enabled: boolean
}

const providers = ref<ProviderItem[]>([])
const models = ref<ModelItem[]>([])
const loading = ref(false)
const defaultEmbeddingModelId = ref<number | null>(null)
const webSearchEnabled = ref(false)
const webSearchProvider = ref<'duckduckgo' | 'serper'>('duckduckgo')
const webSearchSerperEndpoint = ref('https://google.serper.dev/search')
const webSearchSerperApiKey = ref('')
const webSearchSerperHasApiKey = ref(false)

const providerDialogVisible = ref(false)
const modelDialogVisible = ref(false)
const providerDialogMode = ref<'create' | 'edit'>('create')
const modelDialogMode = ref<'create' | 'edit'>('create')
const editingProviderId = ref<number | null>(null)
const editingModelId = ref<number | null>(null)

const providerForm = ref({
  name: '',
  base_url: '',
  api_key: '',
  is_enabled: true,
})

const modelForm = ref({
  provider_id: 0,
  model_name: '',
  display_name: '',
  model_type: 'language',
  description: '',
  tags: '',
  is_enabled: true,
})

const loadProviders = async () => {
  const res = await api.get('/model-settings/providers')
  providers.value = res.data
  if (!modelForm.value.provider_id && providers.value.length > 0) {
    modelForm.value.provider_id = providers.value[0].id
  }
}

const loadModels = async () => {
  const res = await api.get('/model-settings/models')
  models.value = res.data
}

const loadSystem = async () => {
  const res = await api.get('/model-settings/system')
  defaultEmbeddingModelId.value = res.data.default_embedding_model_id || null
  webSearchEnabled.value = !!res.data.web_search_enabled
  webSearchProvider.value = (res.data.web_search_provider || 'duckduckgo') as 'duckduckgo' | 'serper'
  webSearchSerperEndpoint.value = res.data.web_search_serper_endpoint || 'https://google.serper.dev/search'
  webSearchSerperHasApiKey.value = !!res.data.web_search_serper_has_api_key
  webSearchSerperApiKey.value = ''
}

const loadAll = async () => {
  loading.value = true
  try {
    await Promise.all([loadProviders(), loadModels(), loadSystem()])
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || '模型设置加载失败')
  } finally {
    loading.value = false
  }
}

const openCreateProviderDialog = () => {
  providerDialogMode.value = 'create'
  editingProviderId.value = null
  providerForm.value = { name: '', base_url: '', api_key: '', is_enabled: true }
  providerDialogVisible.value = true
}

const openEditProviderDialog = (item: ProviderItem) => {
  providerDialogMode.value = 'edit'
  editingProviderId.value = item.id
  providerForm.value = { name: item.name, base_url: item.base_url, api_key: '', is_enabled: item.is_enabled }
  providerDialogVisible.value = true
}

const submitProviderDialog = async () => {
  try {
    if (providerDialogMode.value === 'create') {
      await api.post('/model-settings/providers', providerForm.value)
      ElMessage.success('供应商已创建')
    } else if (editingProviderId.value) {
      const payload: Record<string, any> = {
        name: providerForm.value.name,
        base_url: providerForm.value.base_url,
        is_enabled: providerForm.value.is_enabled,
      }
      if (providerForm.value.api_key.trim()) payload.api_key = providerForm.value.api_key.trim()
      await api.patch(`/model-settings/providers/${editingProviderId.value}`, payload)
      ElMessage.success('供应商已更新')
    }
    providerDialogVisible.value = false
    await loadAll()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || '提交供应商失败')
  }
}

const deleteProvider = async (item: ProviderItem) => {
  try {
    await ElMessageBox.confirm(`确认删除供应商「${item.name}」？`, '删除供应商', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await api.delete(`/model-settings/providers/${item.id}`)
    await loadAll()
    ElMessage.success('供应商已删除')
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e.response?.data?.detail || e.message || '删除供应商失败')
    }
  }
}

const openCreateModelDialog = () => {
  modelDialogMode.value = 'create'
  editingModelId.value = null
  modelForm.value = {
    provider_id: providers.value[0]?.id || 0,
    model_name: '',
    display_name: '',
    model_type: 'language',
    description: '',
    tags: '',
    is_enabled: true,
  }
  modelDialogVisible.value = true
}

const openEditModelDialog = (item: ModelItem) => {
  modelDialogMode.value = 'edit'
  editingModelId.value = item.id
  modelForm.value = {
    provider_id: item.provider_id,
    model_name: item.model_name,
    display_name: item.display_name,
    model_type: item.model_type,
    description: item.description || '',
    tags: (item.tags || []).join(', '),
    is_enabled: item.is_enabled,
  }
  modelDialogVisible.value = true
}

const submitModelDialog = async () => {
  try {
    const payload = {
      provider_id: modelForm.value.provider_id,
      model_name: modelForm.value.model_name,
      display_name: modelForm.value.display_name,
      model_type: modelForm.value.model_type,
      description: modelForm.value.description,
      tags: modelForm.value.tags
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
      is_enabled: modelForm.value.is_enabled,
    }

    if (modelDialogMode.value === 'create') {
      await api.post('/model-settings/models', payload)
      ElMessage.success('模型已创建')
    } else if (editingModelId.value) {
      await api.patch(`/model-settings/models/${editingModelId.value}`, payload)
      ElMessage.success('模型已更新')
    }
    modelDialogVisible.value = false
    await loadAll()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || '提交模型失败')
  }
}

const deleteModel = async (item: ModelItem) => {
  try {
    await ElMessageBox.confirm(`确认删除模型「${item.display_name}」？`, '删除模型', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await api.delete(`/model-settings/models/${item.id}`)
    await loadAll()
    ElMessage.success('模型已删除')
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e.response?.data?.detail || e.message || '删除模型失败')
    }
  }
}

const testModel = async (item: ModelItem) => {
  try {
    const res = await api.post(`/model-settings/models/${item.id}/test`)
    ElMessage.success(res.data?.message || '测试通过')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || '测试失败')
  }
}

const toggleModelEnabled = async (item: ModelItem, enabled: boolean) => {
  try {
    await api.patch(`/model-settings/models/${item.id}`, { is_enabled: enabled })
    item.is_enabled = enabled
  } catch (e: any) {
    item.is_enabled = !enabled
    ElMessage.error(e.response?.data?.detail || e.message || '更新失败')
  }
}

const setDefaultEmbeddingModel = async () => {
  try {
    const payload: Record<string, any> = {
      default_embedding_model_id: defaultEmbeddingModelId.value,
      web_search_enabled: webSearchEnabled.value,
      web_search_provider: webSearchProvider.value,
      web_search_serper_endpoint: webSearchSerperEndpoint.value,
    }
    if (webSearchProvider.value === 'serper' && webSearchSerperApiKey.value.trim()) {
      payload.web_search_serper_api_key = webSearchSerperApiKey.value.trim()
    }
    await api.patch('/model-settings/system', payload)
    ElMessage.success('系统配置已更新')
    await loadSystem()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || '更新系统配置失败')
  }
}

const modelTypeText = (value: string) => {
  if (value === 'language') return '语言模型'
  if (value === 'vision_language') return '视觉语言模型'
  if (value === 'reasoning') return '推理模型'
  if (value === 'embedding') return 'Embedding'
  return value
}

onMounted(() => {
  void loadAll()
})
</script>

<template>
  <section v-loading="loading" class="model-settings-layout">
    <el-card shadow="never">
      <template #header>
        <div class="card-header-row">
          <span>供应商配置</span>
          <el-button type="primary" size="small" @click="openCreateProviderDialog">添加供应商</el-button>
        </div>
      </template>
      <el-table :data="providers" size="small">
        <el-table-column prop="name" label="名称" width="180" />
        <el-table-column prop="base_url" label="Base URL" min-width="260" />
        <el-table-column label="API Key" width="120">
          <template #default="{ row }">{{ row.has_api_key ? '已配置' : '未配置' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_enabled ? 'success' : 'info'" size="small">{{ row.is_enabled ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="170">
          <template #default="{ row }">
            <el-button text @click="openEditProviderDialog(row)">编辑</el-button>
            <el-button text type="danger" @click="deleteProvider(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-header-row">
          <span>模型配置</span>
          <el-button type="primary" size="small" @click="openCreateModelDialog">添加模型</el-button>
        </div>
      </template>
      <el-table :data="models" size="small">
        <el-table-column prop="display_name" label="显示名" width="180" />
        <el-table-column prop="model_name" label="模型名" min-width="180" />
        <el-table-column prop="provider_name" label="供应商" width="130" />
        <el-table-column label="类型" width="130">
          <template #default="{ row }">{{ modelTypeText(row.model_type) }}</template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="180" />
        <el-table-column label="标签" min-width="160">
          <template #default="{ row }">
            <el-tag v-for="tag in row.tags" :key="`${row.id}-${tag}`" size="small" style="margin-right: 6px">{{ tag }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-switch :model-value="row.is_enabled" @change="(v: any) => toggleModelEnabled(row, !!v)" />
          </template>
        </el-table-column>
        <el-table-column label="测试" width="90">
          <template #default="{ row }">
            <el-button text @click="testModel(row)">测试</el-button>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="170">
          <template #default="{ row }">
            <el-button text @click="openEditModelDialog(row)">编辑</el-button>
            <el-button text type="danger" @click="deleteModel(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-header-row"><span>系统配置</span></div>
      </template>
      <div class="row">
        <el-select v-model="defaultEmbeddingModelId" placeholder="默认 embedding 模型" style="width: 320px">
          <el-option
            v-for="item in models.filter((m) => m.model_type === 'embedding')"
            :key="item.id"
            :label="`${item.display_name} (${item.model_name})`"
            :value="item.id"
          />
        </el-select>
      </div>
      <div class="row" style="margin-top: 12px">
        <el-switch v-model="webSearchEnabled" active-text="启用联网搜索" />
        <el-select v-model="webSearchProvider" style="width: 220px">
          <el-option label="DuckDuckGo（默认）" value="duckduckgo" />
          <el-option label="Serper（中文更优）" value="serper" />
        </el-select>
      </div>
      <div v-if="webSearchProvider === 'serper'" class="row" style="margin-top: 12px">
        <el-input v-model="webSearchSerperEndpoint" placeholder="Serper Endpoint" style="width: 320px" />
        <el-input
          v-model="webSearchSerperApiKey"
          placeholder="Serper API Key（留空则保持现有）"
          show-password
          style="width: 320px"
        />
        <el-tag size="small" :type="webSearchSerperHasApiKey ? 'success' : 'info'">
          {{ webSearchSerperHasApiKey ? '已配置密钥' : '未配置密钥' }}
        </el-tag>
      </div>
      <div class="row" style="margin-top: 12px">
        <el-button type="primary" @click="setDefaultEmbeddingModel">保存系统配置</el-button>
      </div>
    </el-card>

    <el-dialog v-model="providerDialogVisible" :title="providerDialogMode === 'create' ? '添加供应商' : '编辑供应商'" width="560px">
      <el-form label-position="top">
        <el-form-item label="供应商名称">
          <el-input v-model="providerForm.name" placeholder="供应商名称" />
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="providerForm.base_url" placeholder="Base URL" />
        </el-form-item>
        <el-form-item :label="providerDialogMode === 'create' ? 'API Key' : 'API Key（不填则保持原值）'">
          <el-input v-model="providerForm.api_key" placeholder="API Key" show-password />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="providerForm.is_enabled" active-text="启用" inactive-text="停用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="providerDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitProviderDialog">{{ providerDialogMode === 'create' ? '添加' : '保存' }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="modelDialogVisible" :title="modelDialogMode === 'create' ? '添加模型' : '编辑模型'" width="620px">
      <el-form label-position="top">
        <el-form-item label="供应商">
          <el-select v-model="modelForm.provider_id" placeholder="选择供应商" style="width: 100%">
            <el-option v-for="item in providers" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型名（API）">
          <el-input v-model="modelForm.model_name" placeholder="模型名（API）" />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="modelForm.display_name" placeholder="显示名" />
        </el-form-item>
        <el-form-item label="模型类型">
          <el-select v-model="modelForm.model_type" style="width: 100%">
            <el-option label="语言模型" value="language" />
            <el-option label="视觉语言模型" value="vision_language" />
            <el-option label="推理模型" value="reasoning" />
            <el-option label="Embedding" value="embedding" />
          </el-select>
        </el-form-item>
        <el-form-item label="简短描述">
          <el-input v-model="modelForm.description" placeholder="简短描述" />
        </el-form-item>
        <el-form-item label="标签（逗号分隔）">
          <el-input v-model="modelForm.tags" placeholder="标签，逗号分隔" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="modelForm.is_enabled" active-text="启用" inactive-text="停用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="modelDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitModelDialog">{{ modelDialogMode === 'create' ? '添加' : '保存' }}</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.model-settings-layout {
  display: grid;
  gap: 12px;
}
</style>
