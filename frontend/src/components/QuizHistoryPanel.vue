<script setup lang="ts">
import { ref } from 'vue'

import api from '../api/client'

type QuizHistoryItem = {
  attempt_id: number
  score: number | null
  total_questions: number
  created_at: string
}

type WrongQuestionItem = {
  attempt_id: number
  index: number
  question: string
  your_answer: string
  correct_answer: string
  type: string
}

const history = ref<QuizHistoryItem[]>([])
const wrongQuestions = ref<WrongQuestionItem[]>([])
const loadingHistory = ref(false)
const loadingWrong = ref(false)
const retryStatus = ref('')

const loadHistory = async () => {
  loadingHistory.value = true
  try {
    const res = await api.get('/quiz/history?limit=10')
    history.value = res.data
  } finally {
    loadingHistory.value = false
  }
}

const loadWrongQuestions = async () => {
  loadingWrong.value = true
  try {
    const res = await api.get('/quiz/wrong-questions?limit=20')
    wrongQuestions.value = res.data
  } finally {
    loadingWrong.value = false
  }
}

const retryWrongQuestions = async () => {
  retryStatus.value = ''
  const res = await api.post('/quiz/retry-wrong?limit=20')
  const count = res.data.source_wrong_count || 0
  if (count === 0) {
    retryStatus.value = '当前没有可重练错题'
    return
  }
  retryStatus.value = `已生成错题重练 attempt #${res.data.attempt_id}（${count}题）`
  await loadHistory()
}
</script>

<template>
  <section>
    <h3>练习历史与错题本</h3>
    <div style="display: flex; gap: 8px">
      <button @click="loadHistory">{{ loadingHistory ? '加载历史中...' : '刷新练习历史' }}</button>
      <button @click="loadWrongQuestions">{{ loadingWrong ? '加载错题中...' : '刷新错题本' }}</button>
      <button @click="retryWrongQuestions">一键重练错题</button>
    </div>
    <p v-if="retryStatus" style="margin-top: 8px; color: #2f6b2f">{{ retryStatus }}</p>

    <div style="margin-top: 10px">
      <h4>练习历史</h4>
      <div v-for="item in history" :key="item.attempt_id" style="border-top: 1px solid #ddd; padding: 6px 0">
        <p>
          attempt #{{ item.attempt_id }} |
          score: {{ item.score === null ? '未提交' : (item.score * 100).toFixed(1) + '%' }} |
          questions: {{ item.total_questions }}
        </p>
        <p style="font-size: 12px; color: #666">{{ item.created_at }}</p>
      </div>
    </div>

    <div style="margin-top: 10px">
      <h4>错题本</h4>
      <div v-for="item in wrongQuestions" :key="`${item.attempt_id}-${item.index}`" style="border-top: 1px solid #ddd; padding: 6px 0">
        <p><strong>{{ item.type }}</strong> | attempt #{{ item.attempt_id }} | Q{{ item.index + 1 }}</p>
        <p>{{ item.question }}</p>
        <p>你的答案: {{ item.your_answer }} | 正确答案: {{ item.correct_answer }}</p>
      </div>
    </div>
  </section>
</template>
