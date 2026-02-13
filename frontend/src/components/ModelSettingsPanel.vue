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

const createProvider = async () => {
  try {
    await api.post('/model-settings/providers', providerForm.value)
    providerForm.value = { name: '', base_url: '', api_key: '', is_enabled: true }
    await loadAll()
    ElMessage.success('供应商已创建')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || '创建供应商失败')
  }
}

const createModel = async () => {
  try {
    const payload = {
      ...modelForm.value,
      tags: modelForm.value.tags
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
    }
    await api.post('/model-settings/models', payload)
    modelForm.value = {
      provider_id: providers.value[0]?.id || 0,
      model_name: '',
      display_name: '',
      model_type: 'language',
      description: '',
      tags: '',
      is_enabled: true,
    }
    await loadAll()
    ElMessage.success('模型已创建')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || e.message || '创建模型失败')
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

const deleteProviderGuard = async () => {
  await ElMessageBox.alert('当前版本暂不提供删除供应商，避免误删后影响历史模型映射。', '提示', {
    confirmButtonText: '知道了',
  })
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
        <div class="card-header-row"><span>供应商配置</span></div>
      </template>
      <div class="model-form-grid">
        <el-input v-model="providerForm.name" placeholder="供应商名称" />
        <el-input v-model="providerForm.base_url" placeholder="Base URL" />
        <el-input v-model="providerForm.api_key" placeholder="API Key" show-password />
        <el-button type="primary" @click="createProvider">新增供应商</el-button>
      </div>
      <el-table :data="providers" size="small" style="margin-top: 12px">
        <el-table-column prop="name" label="名称" width="160" />
        <el-table-column prop="base_url" label="Base URL" min-width="220" />
        <el-table-column label="API Key" width="110">
          <template #default="{ row }">{{ row.has_api_key ? '已配置' : '未配置' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_enabled ? 'success' : 'info'" size="small">{{ row.is_enabled ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default>
            <el-button text @click="deleteProviderGuard">说明</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-header-row"><span>模型配置</span></div>
      </template>
      <div class="model-form-grid model-form-grid--models">
        <el-select v-model="modelForm.provider_id" placeholder="选择供应商">
          <el-option v-for="item in providers" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
        <el-input v-model="modelForm.model_name" placeholder="模型名（API）" />
        <el-input v-model="modelForm.display_name" placeholder="显示名" />
        <el-select v-model="modelForm.model_type">
          <el-option label="语言模型" value="language" />
          <el-option label="视觉语言模型" value="vision_language" />
          <el-option label="推理模型" value="reasoning" />
          <el-option label="Embedding" value="embedding" />
        </el-select>
        <el-input v-model="modelForm.description" placeholder="简短描述" />
        <el-input v-model="modelForm.tags" placeholder="标签，逗号分隔" />
        <el-button type="primary" @click="createModel">新增模型</el-button>
      </div>
      <el-table :data="models" size="small" style="margin-top: 12px">
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
  </section>
</template>
