<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import api from '../api/client'

const memory = ref<any>(null)
const loading = ref(false)

const refresh = async () => {
  loading.value = true
  try {
    const res = await api.get('/memory/profile')
    memory.value = res.data
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div>
    <el-button :loading="loading" @click="refresh">刷新画像</el-button>
    <el-descriptions v-if="memory" :column="1" border style="margin-top: 12px">
      <el-descriptions-item label="最近难度">{{ memory.last_difficulty }}</el-descriptions-item>
      <el-descriptions-item label="薄弱知识点">{{ (memory.weak_points || []).join(', ') || '无' }}</el-descriptions-item>
      <el-descriptions-item label="掌握度JSON">
        <pre style="margin: 0">{{ JSON.stringify(memory.mastery || {}, null, 2) }}</pre>
      </el-descriptions-item>
    </el-descriptions>
  </div>
</template>
