<script setup lang="ts">
import { ref } from 'vue'

import api from '../api/client'

const status = ref('')

const onFile = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) {
    return
  }

  const formData = new FormData()
  formData.append('file', file)

  const res = await api.post('/knowledge/upload', formData)
  status.value = `上传成功，文档ID=${res.data.document_id}，切片=${res.data.chunks}`
}
</script>

<template>
  <section>
    <h3>知识库上传</h3>
    <input type="file" @change="onFile" />
    <p>{{ status }}</p>
  </section>
</template>
