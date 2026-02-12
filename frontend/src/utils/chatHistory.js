export function orderConversation(turns) {
  return [...turns].sort((a, b) => {
    const ta = new Date(a.created_at).getTime()
    const tb = new Date(b.created_at).getTime()
    return ta - tb
  })
}

export function findConversationIndex(orderedTurns, turnId) {
  return orderedTurns.findIndex((turn) => turn.id === turnId)
}
