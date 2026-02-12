<script setup lang="ts">
import KnowledgeUpload from '../components/KnowledgeUpload.vue'
import MemoryPanel from '../components/MemoryPanel.vue'
import QuizPanel from '../components/QuizPanel.vue'
import QuizHistoryPanel from '../components/QuizHistoryPanel.vue'
import ChatWorkspace from '../components/ChatWorkspace.vue'
</script>

<template>
  <main style="max-width: 1200px; margin: 2rem auto; display: grid; gap: 24px; font-family: sans-serif">
    <h1>法语学习系统 MVP</h1>
    <ChatWorkspace />
    <KnowledgeUpload />
    <QuizPanel />
    <QuizHistoryPanel />
    <MemoryPanel />
  </main>
</template>
