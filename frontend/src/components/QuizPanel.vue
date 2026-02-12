<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import api from '../api/client'

const attemptId = ref<number | null>(null)
const questions = ref<any[]>([])
const answers = ref<string[]>([])
const result = ref('')
const loading = ref(false)

const generate = async () => {
  loading.value = true
  try {
    const res = await api.post('/quiz/generate', { num_questions: 6 })
    attemptId.value = res.data.attempt_id
    questions.value = res.data.questions
    answers.value = new Array(questions.value.length).fill('')
    result.value = ''
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '生成失败')
  } finally {
    loading.value = false
  }
}

const submit = async () => {
  if (!attemptId.value) return
  try {
    const res = await api.post('/quiz/submit', { attempt_id: attemptId.value, answers: answers.value })
    result.value = `得分 ${res.data.correct}/${res.data.total}（${(res.data.score * 100).toFixed(1)}%）`
    ElMessage.success('提交成功')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '提交失败')
  }
}
</script>

<template>
  <div>
    <el-button type="primary" :loading="loading" @click="generate">生成练习</el-button>
    <el-space direction="vertical" fill style="width: 100%; margin-top: 12px">
      <el-card v-for="(q, i) in questions" :key="i" shadow="never">
        <div>{{ i + 1 }}. {{ q.prompt }}</div>
        <el-input v-model="answers[i]" placeholder="请输入你的答案" style="margin-top: 8px" />
      </el-card>
    </el-space>
    <div class="row" style="margin-top: 12px">
      <el-button v-if="questions.length" type="success" @click="submit">提交答案</el-button>
      <el-tag v-if="result" type="info">{{ result }}</el-tag>
    </div>
  </div>
</template>
