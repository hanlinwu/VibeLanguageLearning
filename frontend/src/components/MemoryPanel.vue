<script setup lang="ts">
import { ref } from 'vue'

import api from '../api/client'

const memory = ref<any>(null)

const refresh = async () => {
  const res = await api.get('/memory/profile')
  memory.value = res.data
}
</script>

<template>
  <section>
    <h3>学习画像</h3>
    <button @click="refresh">刷新画像</button>
    <pre v-if="memory">{{ JSON.stringify(memory, null, 2) }}</pre>
  </section>
</template>
