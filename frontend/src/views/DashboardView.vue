<script setup lang="ts">
import KnowledgeUpload from '../components/KnowledgeUpload.vue'
import MemoryPanel from '../components/MemoryPanel.vue'
import QueryPanel from '../components/QueryPanel.vue'
import QuizPanel from '../components/QuizPanel.vue'
import InteractionPanel from '../components/InteractionPanel.vue'
import QuizHistoryPanel from '../components/QuizHistoryPanel.vue'
</script>

<template>
  <main style="max-width: 960px; margin: 2rem auto; display: grid; gap: 24px; font-family: sans-serif">
    <h1>法语学习系统 MVP</h1>
    <KnowledgeUpload />
    <QueryPanel />
    <InteractionPanel />
    <QuizPanel />
    <QuizHistoryPanel />
    <MemoryPanel />
  </main>
</template>
