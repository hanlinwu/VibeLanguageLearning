<script setup lang="ts">
import { ref } from 'vue'

import api from '../api/client'

type InteractionItem = {
  id: number
  question: string
  answer: string
  trace_id: string
  created_at: string
}

const history = ref<InteractionItem[]>([])
const loading = ref(false)

const loadHistory = async () => {
  loading.value = true
  try {
    const res = await api.get('/interactions/recent?limit=10')
    history.value = res.data
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section>
    <h3>对话历史</h3>
    <button @click="loadHistory">{{ loading ? '加载中...' : '刷新历史' }}</button>
    <div v-for="item in history" :key="item.id" style="margin-top: 10px; border-top: 1px solid #ddd; padding-top: 8px">
      <p><strong>Q:</strong> {{ item.question }}</p>
      <p><strong>A:</strong> {{ item.answer }}</p>
      <p style="font-size: 12px; color: #666">trace: {{ item.trace_id }} | {{ item.created_at }}</p>
    </div>
  </section>
</template>
