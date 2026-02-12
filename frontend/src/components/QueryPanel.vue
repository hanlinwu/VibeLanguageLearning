<script setup lang="ts">
import { ref } from 'vue'

import api from '../api/client'

const question = ref('')
const answer = ref('')
const citations = ref<any[]>([])

const ask = async () => {
  const res = await api.post('/query', { question: question.value })
  answer.value = res.data.answer
  citations.value = res.data.citations
}
</script>

<template>
  <section>
    <h3>知识点查询（RAG）</h3>
    <input v-model="question" placeholder="输入你的法语问题" style="width: 100%; padding: 8px" />
    <button @click="ask" style="margin-top: 8px">提问</button>
    <p><strong>回答:</strong> {{ answer }}</p>
    <ul>
      <li v-for="item in citations" :key="item.chunk_id">chunk {{ item.chunk_id }}: {{ item.preview }}</li>
    </ul>
  </section>
</template>
