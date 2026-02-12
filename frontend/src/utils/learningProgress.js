export function summarizeProgress(memoryProfile) {
  const mastery = memoryProfile?.mastery || {}
  const weakPoints = Array.isArray(memoryProfile?.weak_points) ? memoryProfile.weak_points : []

  const values = Object.values(mastery)
  const masteredCount = values.filter((value) => Number(value) >= 0.7).length
  const learningCount = values.filter((value) => Number(value) >= 0.4 && Number(value) < 0.7).length

  return {
    masteredCount,
    learningCount,
    weakCount: weakPoints.length,
    totalTopics: values.length,
  }
}
