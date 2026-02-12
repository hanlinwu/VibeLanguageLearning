import { defineStore } from 'pinia'

import api from '../api/client'

export type ConversationItem = {
  id: number
  title: string
  created_at: string
  updated_at: string
}

export const useChatStore = defineStore('chat', {
  state: () => ({
    conversations: [] as ConversationItem[],
    activeConversationId: null as number | null,
  }),
  actions: {
    async loadConversations() {
      const res = await api.get('/interactions/conversations?limit=50')
      this.conversations = res.data
    },
    setActiveConversation(conversationId: number | null) {
      this.activeConversationId = conversationId
    },
    startNewConversation() {
      this.activeConversationId = null
    },
  },
})
