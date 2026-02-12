<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import api from '../api/client'

const memory = ref<any>(null)
const memoryStream = ref<{ items: any[]; changes: any[] }>({ items: [], changes: [] })
const loading = ref(false)

const refresh = async () => {
  loading.value = true
  try {
    const [profileRes, streamRes] = await Promise.all([
      api.get('/memory/profile'),
      api.get('/memory/stream'),
    ])
    memory.value = profileRes.data
    memoryStream.value = streamRes.data
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

const deleteItem = async (itemId: number) => {
  try {
    await api.delete(`/memory/items/${itemId}`)
    ElMessage.success('记忆项已删除')
    await refresh()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

onMounted(() => {
  void refresh()
})
</script>

<template>
  <div>
    <el-button :loading="loading" @click="refresh">刷新进展</el-button>
    <el-descriptions v-if="memory" :column="1" border style="margin-top: 12px">
      <el-descriptions-item label="最近难度">{{ memory.last_difficulty }}</el-descriptions-item>
      <el-descriptions-item label="薄弱知识点">{{ (memory.weak_points || []).join(', ') || '无' }}</el-descriptions-item>
      <el-descriptions-item label="掌握度JSON">
        <pre style="margin: 0">{{ JSON.stringify(memory.mastery || {}, null, 2) }}</pre>
      </el-descriptions-item>
    </el-descriptions>

    <el-card style="margin-top: 14px" shadow="never">
      <template #header>
        <div class="card-header-row">
          <span>长期记忆流（活跃）</span>
        </div>
      </template>
      <el-empty v-if="!memoryStream.items.length" description="暂无重要记忆" />
      <el-space v-else direction="vertical" fill>
        <el-card v-for="item in memoryStream.items" :key="item.id" shadow="hover">
          <div class="row" style="justify-content: space-between">
            <div class="row">
              <el-tag size="small">{{ item.category }}</el-tag>
              <strong>{{ item.memory_key }}</strong>
            </div>
            <el-button type="danger" text size="small" @click="deleteItem(item.id)">删除</el-button>
          </div>
          <div style="margin-top: 8px">{{ item.content }}</div>
          <div style="margin-top: 6px; color: #8a94a6; font-size: 12px">
            重要度: {{ Number(item.importance).toFixed(2) }} · 更新时间: {{ item.updated_at }}
          </div>
        </el-card>
      </el-space>
    </el-card>

    <el-card style="margin-top: 14px" shadow="never">
      <template #header>
        <div class="card-header-row">
          <span>记忆变更历史</span>
        </div>
      </template>
      <el-empty v-if="!memoryStream.changes.length" description="暂无变更历史" />
      <el-timeline v-else>
        <el-timeline-item
          v-for="change in memoryStream.changes"
          :key="change.id"
          :timestamp="change.created_at"
          :type="change.action === 'create' ? 'success' : change.action === 'update' ? 'warning' : 'danger'"
        >
          <div><strong>{{ change.action.toUpperCase() }}</strong> · item#{{ change.item_id || '-' }}</div>
          <div style="color: #8a94a6; font-size: 12px">原因：{{ change.reason || '-' }}</div>
        </el-timeline-item>
      </el-timeline>
    </el-card>
  </div>
</template>
