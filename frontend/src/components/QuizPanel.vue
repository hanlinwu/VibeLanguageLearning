<script setup lang="ts">
import { ref } from 'vue'

import api from '../api/client'

const attemptId = ref<number | null>(null)
const questions = ref<any[]>([])
const answers = ref<string[]>([])
const result = ref('')

const generate = async () => {
  const res = await api.post('/quiz/generate', { num_questions: 6 })
  attemptId.value = res.data.attempt_id
  questions.value = res.data.questions
  answers.value = new Array(questions.value.length).fill('')
}

const submit = async () => {
  if (!attemptId.value) return
  const res = await api.post('/quiz/submit', { attempt_id: attemptId.value, answers: answers.value })
  result.value = `得分: ${res.data.correct}/${res.data.total} (${(res.data.score * 100).toFixed(1)}%)`
}
</script>

<template>
  <section>
    <h3>动态出题</h3>
    <button @click="generate">生成练习</button>
    <div v-for="(q, i) in questions" :key="i" style="margin: 8px 0">
      <p>{{ i + 1 }}. {{ q.prompt }}</p>
      <input v-model="answers[i]" placeholder="你的答案" />
    </div>
    <button v-if="questions.length" @click="submit">提交答案</button>
    <p>{{ result }}</p>
  </section>
</template>
