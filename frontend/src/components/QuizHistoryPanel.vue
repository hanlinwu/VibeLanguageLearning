<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

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
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载历史失败')
  } finally {
    loadingHistory.value = false
  }
}

const loadWrongQuestions = async () => {
  loadingWrong.value = true
  try {
    const res = await api.get('/quiz/wrong-questions?limit=20')
    wrongQuestions.value = res.data
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载错题失败')
  } finally {
    loadingWrong.value = false
  }
}

const retryWrongQuestions = async () => {
  retryStatus.value = ''
  try {
    const res = await api.post('/quiz/retry-wrong?limit=20')
    const count = res.data.source_wrong_count || 0
    if (count === 0) {
      retryStatus.value = '当前没有可重练错题'
      return
    }
    retryStatus.value = `已生成错题重练 attempt #${res.data.attempt_id}（${count}题）`
    await loadHistory()
    ElMessage.success('错题重练已生成')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '生成错题重练失败')
  }
}
</script>

<template>
  <div>
    <div class="row" style="margin-bottom: 12px">
      <el-button :loading="loadingHistory" @click="loadHistory">刷新练习历史</el-button>
      <el-button :loading="loadingWrong" @click="loadWrongQuestions">刷新错题本</el-button>
      <el-button type="warning" @click="retryWrongQuestions">一键重练错题</el-button>
    </div>

    <el-alert v-if="retryStatus" :title="retryStatus" type="success" :closable="false" style="margin-bottom: 12px" />

    <el-table :data="history" border style="margin-bottom: 16px">
      <el-table-column prop="attempt_id" label="Attempt" width="120" />
      <el-table-column label="分数">
        <template #default="scope">
          {{ scope.row.score === null ? '未提交' : `${(scope.row.score * 100).toFixed(1)}%` }}
        </template>
      </el-table-column>
      <el-table-column prop="total_questions" label="题数" width="100" />
      <el-table-column prop="created_at" label="时间" min-width="200" />
    </el-table>

    <el-table :data="wrongQuestions" border>
      <el-table-column prop="attempt_id" label="Attempt" width="120" />
      <el-table-column prop="index" label="题号" width="90" />
      <el-table-column prop="type" label="题型" width="120" />
      <el-table-column prop="question" label="题目" min-width="260" />
      <el-table-column prop="your_answer" label="你的答案" width="120" />
      <el-table-column prop="correct_answer" label="正确答案" width="120" />
    </el-table>
  </div>
</template>
