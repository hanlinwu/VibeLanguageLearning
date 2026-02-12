<script setup lang="ts">
import QuizHistoryPanel from '../components/QuizHistoryPanel.vue'
import QuizPanel from '../components/QuizPanel.vue'
</script>

<template>
  <section style="display: grid; gap: 16px">
    <div class="module-card">
      <h2 class="page-title">练习生成与作答</h2>
      <QuizPanel />
    </div>
    <div class="module-card">
      <h2 class="page-title">练习历史与错题本</h2>
      <QuizHistoryPanel />
    </div>
  </section>
</template>
