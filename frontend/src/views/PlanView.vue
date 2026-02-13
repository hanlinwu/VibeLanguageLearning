<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Loading, Switch } from '@element-plus/icons-vue'

import api from '../api/client'

type LanguageCode = 'en' | 'fr' | 'ja'

interface LanguageProfile {
  id: number
  language_code: LanguageCode
  language_label: string
  is_active: boolean
}

interface PlanClass {
  id: number
  class_index: number
  title: string
  description: string | null
  content_json: Record<string, any> | null
  is_completed: boolean
  completed_at: string | null
  last_assessment_score: number | null
}

interface PlanSection {
  section_index: number
  title: string
  classes: PlanClass[]
}

interface StudyLevel {
  id: number
  level_index: number
  title: string
  objective: string | null
  generated_detail: boolean
  sections: PlanSection[]
}

interface StudyPlan {
  id: number
  title: string
  description: string | null
  status: string
  generation?: {
    target_levels: number
    generated_levels: number
    is_complete: boolean
  }
  levels: StudyLevel[]
}

interface PlanListItem {
  id: number
  language_code: string
  language_label: string
  title: string
  status: string
  level_count: number
  generation?: {
    target_levels: number
    generated_levels: number
    is_complete: boolean
  }
}

const loading = ref(false)
const creating = ref(false)
const plans = ref<PlanListItem[]>([])
const currentLanguage = ref<LanguageProfile | null>(null)
const currentPlan = ref<StudyPlan | null>(null)
const generationStatus = ref<{
  plan_id: number
  job_id: string | null
  status: 'idle' | 'running' | 'completed' | 'failed'
  generated_levels: number
  target_levels: number
  current_step: string | null
  error: string | null
} | null>(null)
const selectedNewLanguage = ref<LanguageCode>('en')
const questionnaireVisible = ref(false)
const assessmentDialogVisible = ref(false)
const assessmentLoading = ref(false)
const assessmentStarting = ref(false)
const assessmentSubmitting = ref(false)
const assessmentClass = ref<PlanClass | null>(null)
const assessmentCurrentQuestion = ref<any | null>(null)
const assessmentCurrentAnswer = ref('')
const assessmentHistory = ref<Array<{ question: any; answer: string }>>([])
const assessmentQuestionIndex = ref(1)
const assessmentTotalQuestions = ref(5)
const assessmentAttemptId = ref<number | null>(null)

const questionnaire = reactive({
  current_level: '入门生存交流',
  self_assessment: '',
  target_level: '日常交流',
  target_duration_weeks: 24,
  learning_experience: '',
  preferred_focus: '',
})

const parseApiError = (e: any, fallback: string) => {
  const detail = e?.response?.data?.detail
  if (Array.isArray(detail)) {
    const text = detail
      .map((item: any) => {
        const loc = Array.isArray(item?.loc) ? item.loc.join('.') : ''
        const msg = item?.msg || ''
        return [loc, msg].filter(Boolean).join(': ')
      })
      .filter(Boolean)
      .join('；')
    if (text) return text
  }
  if (typeof detail === 'string' && detail.trim()) return detail
  return e?.message || fallback
}

const languageChoices = [
  { code: 'en' as LanguageCode, label: '英语', sub: 'English', emoji: 'EN' },
  { code: 'fr' as LanguageCode, label: '法语', sub: 'Français', emoji: 'FR' },
  { code: 'ja' as LanguageCode, label: '日语', sub: '日本語', emoji: 'JA' },
]

const targetLevelOptions = [
  { label: '入门生存交流（能应对问候/点餐/问路）', value: '入门生存交流' },
  { label: '日常交流（能聊日常话题并持续对话）', value: '日常交流' },
  { label: '工作与学习表达（能做结构化表达）', value: '工作与学习表达' },
  { label: '接近母语流利（复杂话题稳定输出）', value: '接近母语流利' },
]

const currentLevelOptions = [
  { label: '零基础（从字母/发音开始）', value: '零基础' },
  ...targetLevelOptions,
]

const languageChoiceMap = computed(() => {
  const map = new Map<LanguageCode, { code: LanguageCode; label: string; sub: string; emoji: string }>()
  for (const item of languageChoices) map.set(item.code, item)
  return map
})

const sortedPlans = computed(() => {
  return [...plans.value].sort((a, b) => Number(b.status === 'active') - Number(a.status === 'active'))
})
const isGenerating = computed(() => generationStatus.value?.status === 'running')
const isPlanGenerating = (item: PlanListItem) => !!item.generation && !item.generation.is_complete
const planProgressText = (item: PlanListItem) =>
  `${item.generation?.generated_levels || item.level_count}/${item.generation?.target_levels || 0} levels`

let generationPollTimer: number | null = null

const clearGenerationPolling = () => {
  if (generationPollTimer !== null) {
    window.clearInterval(generationPollTimer)
    generationPollTimer = null
  }
}

const fetchPlans = async () => {
  const res = await api.get('/plans')
  plans.value = (res.data?.plans || []) as PlanListItem[]
}

const fetchCurrentPlan = async () => {
  const res = await api.get('/plans/current')
  currentLanguage.value = (res.data?.language || null) as LanguageProfile | null
  currentPlan.value = (res.data?.plan || null) as StudyPlan | null
}

const refreshPlanData = async () => {
  await Promise.all([fetchPlans(), fetchCurrentPlan()])
}

const initPage = async () => {
  loading.value = true
  try {
    await refreshPlanData()
  } catch (e: any) {
    ElMessage.error(parseApiError(e, '加载计划失败'))
  } finally {
    loading.value = false
  }
}

const openCreatePlan = () => {
  questionnaireVisible.value = true
}

const hasPendingLevelDetails = (plan: StudyPlan | null) => {
  if (!plan) return false
  return (plan.levels || []).some((level) => !level.generated_detail)
}

const shouldContinueAutoGeneration = (plan: StudyPlan | null) => {
  if (!plan) return false
  const g = plan.generation
  const notFinished = !!g && !g.is_complete
  return notFinished || hasPendingLevelDetails(plan)
}

const pollGenerationStatus = async (targetPlanId: number) => {
  try {
    const res = await api.get(`/plans/${targetPlanId}/generation/status`)
    generationStatus.value = res.data || null
    await refreshPlanData()
    const status = generationStatus.value?.status
    if (status === 'completed') {
      clearGenerationPolling()
    } else if (status === 'failed') {
      clearGenerationPolling()
      ElMessage.error(generationStatus.value?.error || '计划生成失败')
    } else if (status === 'idle') {
      const plan = currentPlan.value
      if (!plan || plan.id !== targetPlanId || !shouldContinueAutoGeneration(plan)) {
        clearGenerationPolling()
      }
    }
  } catch (e: any) {
    clearGenerationPolling()
    ElMessage.error(parseApiError(e, '获取生成进度失败'))
  }
}

const startPlanGeneration = async (targetPlanId: number, silent = false) => {
  try {
    const res = await api.post(`/plans/${targetPlanId}/generation/start`)
    generationStatus.value = res.data || null
    await refreshPlanData()
    clearGenerationPolling()
    generationPollTimer = window.setInterval(() => {
      void pollGenerationStatus(targetPlanId)
    }, 2500)
    void pollGenerationStatus(targetPlanId)
    if (!silent && generationStatus.value?.status === 'running') {
      ElMessage.success('系统正在后台生成完整学习计划')
    }
  } catch (e: any) {
    if (!silent) {
      ElMessage.error(parseApiError(e, '启动计划生成失败'))
    }
  }
}

const submitCreatePlan = async () => {
  if (!questionnaire.self_assessment.trim()) {
    ElMessage.warning('请填写当前掌握情况自评')
    return
  }
  try {
    creating.value = true
    const res = await api.post('/plans', {
      language_code: selectedNewLanguage.value,
      current_level: questionnaire.current_level,
      self_assessment: questionnaire.self_assessment.trim(),
      target_level: questionnaire.target_level,
      target_duration_weeks: questionnaire.target_duration_weeks,
      learning_experience: questionnaire.learning_experience.trim() || null,
      preferred_focus: questionnaire.preferred_focus.trim() || null,
    })
    questionnaireVisible.value = false
    const planId = res.data?.plan?.id
    await refreshPlanData()
    if (planId) {
      void startPlanGeneration(planId, true)
    }
    ElMessage.success('学习计划已创建，系统将在后台自动生成完整路径')
  } catch (e: any) {
    ElMessage.error(parseApiError(e, '创建计划失败'))
  } finally {
    creating.value = false
  }
}

const activatePlan = async (planId: number) => {
  try {
    await api.patch(`/plans/${planId}/activate`)
    await refreshPlanData()
    void startPlanGeneration(planId, true)
    ElMessage.success('已切换激活计划')
  } catch (e: any) {
    ElMessage.error(parseApiError(e, '切换失败'))
  }
}

const deletePlan = async (planId: number, title: string) => {
  try {
    await ElMessageBox.confirm(`确认永久删除计划「${title}」？该操作不可恢复。`, '删除计划', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await api.delete(`/plans/${planId}`)
    await refreshPlanData()
    ElMessage.success('计划已删除')
  } catch {
    // ignore cancel
  }
}

const openClassAssessment = async (cls: PlanClass) => {
  assessmentClass.value = cls
  assessmentCurrentQuestion.value = null
  assessmentCurrentAnswer.value = ''
  assessmentHistory.value = []
  assessmentQuestionIndex.value = 1
  assessmentTotalQuestions.value = 5
  assessmentAttemptId.value = null
  assessmentDialogVisible.value = true
  try {
    assessmentLoading.value = true
    assessmentStarting.value = true
    const res = await api.post(`/plans/classes/${cls.id}/assessment/start`)
    assessmentCurrentQuestion.value = res.data?.question || null
    assessmentCurrentAnswer.value = ''
    assessmentHistory.value = []
    assessmentQuestionIndex.value = res.data?.question_index || 1
    assessmentTotalQuestions.value = res.data?.total_questions || 5
    assessmentAttemptId.value = res.data?.attempt_id || null
    assessmentDialogVisible.value = true
  } catch (e: any) {
    ElMessage.error(parseApiError(e, '生成测评失败'))
    assessmentDialogVisible.value = false
  } finally {
    assessmentLoading.value = false
    assessmentStarting.value = false
  }
}

const submitClassAssessment = async () => {
  if (!assessmentClass.value || !assessmentAttemptId.value || !assessmentCurrentQuestion.value) return
  if (!String(assessmentCurrentAnswer.value || '').trim()) {
    ElMessage.warning('请先作答再继续')
    return
  }
  try {
    assessmentSubmitting.value = true
    const answerText = String(assessmentCurrentAnswer.value || '').trim()
    const currentQuestion = assessmentCurrentQuestion.value
    assessmentHistory.value.push({ question: currentQuestion, answer: answerText })

    const res = await api.post(`/plans/classes/${assessmentClass.value.id}/assessment/step`, {
      attempt_id: assessmentAttemptId.value,
      answer: answerText,
    })
    const body = res.data || {}
    if (body.done) {
      if (body.passed) {
        ElMessage.success(
          `测评通过（${Math.round((body.score || 0) * 100)}分），已将当前及前序关卡标记为完成`
        )
      } else {
        ElMessage.warning(`测评未通过（${Math.round((body.score || 0) * 100)}分），可继续练习后重测`)
      }
      assessmentDialogVisible.value = false
      await refreshPlanData()
      return
    }
    assessmentCurrentQuestion.value = body.question || null
    assessmentQuestionIndex.value = body.question_index || assessmentQuestionIndex.value + 1
    assessmentCurrentAnswer.value = ''
  } catch (e: any) {
    ElMessage.error(parseApiError(e, '提交测评失败'))
  } finally {
    assessmentSubmitting.value = false
  }
}

const letterLabel = (idx: number) => String.fromCharCode(65 + idx)

onMounted(async () => {
  await initPage()
  if (currentPlan.value && shouldContinueAutoGeneration(currentPlan.value)) {
    void startPlanGeneration(currentPlan.value.id, true)
  }
})

onBeforeUnmount(() => {
  clearGenerationPolling()
})
</script>

<template>
  <section class="module-card plan-page" v-loading="loading">
    <h2 class="page-title">我的学习计划</h2>

    <el-card shadow="never" class="plan-language-panel">
      <div class="plan-plan-grid">
        <button
          v-for="item in sortedPlans"
          :key="item.id"
          type="button"
          class="plan-language-card"
          :class="{ active: item.status === 'active', generating: isPlanGenerating(item) }"
          @click="activatePlan(item.id)"
        >
          <div class="plan-language-top">
            <span class="plan-language-emoji">{{ languageChoiceMap.get(item.language_code as LanguageCode)?.emoji || 'LG' }}</span>
            <el-tag :type="item.status === 'active' ? 'primary' : 'info'" effect="plain" size="small">
              {{ item.status === 'active' ? '当前激活' : '可切换' }}
            </el-tag>
          </div>
          <div class="plan-language-name">{{ item.title }}</div>
          <div class="plan-language-sub">{{ item.language_label }} · {{ planProgressText(item) }}</div>
          <div class="plan-generation-state" :class="{ done: !isPlanGenerating(item) }">
            <span v-if="isPlanGenerating(item)" class="plan-generation-dot" />
            {{ isPlanGenerating(item) ? '正在生成计划内容' : '已创建完成' }}
          </div>
          <div class="plan-card-actions">
            <el-button size="small" :icon="Switch" @click.stop="activatePlan(item.id)">激活</el-button>
            <el-button size="small" type="danger" plain :icon="Delete" @click.stop="deletePlan(item.id, item.title)">删除</el-button>
          </div>
        </button>

        <button type="button" class="plan-language-card plan-language-card--create" @click="openCreatePlan">
          <div class="plan-language-top">
            <span class="plan-language-emoji">＋</span>
            <el-tag type="info" effect="plain" size="small">新建</el-tag>
          </div>
          <div class="plan-language-name">创建新计划</div>
          <div class="plan-language-sub">通过问卷选择语言并自动生成完整计划</div>
        </button>
      </div>
    </el-card>

    <el-card shadow="never" class="plan-roadmap-panel">
      <template v-if="currentLanguage && currentPlan">
        <div class="plan-roadmap-header">
          <div>
            <h3>{{ currentPlan.title }}</h3>
          </div>
          <el-tag v-if="isGenerating" type="primary" effect="plain">
            正在自动生成计划内容（{{ generationStatus?.generated_levels || currentPlan.levels.length }}/{{ generationStatus?.target_levels || currentPlan.generation?.target_levels || 0 }}）
          </el-tag>
        </div>

        <div class="plan-levels">
          <el-card
            v-for="level in currentPlan.levels"
            :key="level.id"
            shadow="never"
            class="plan-level-card"
          >
            <div class="plan-level-title-row">
              <div>
                <div class="plan-level-index">Level {{ level.level_index }}</div>
                <h4>{{ level.title }}</h4>
                <p>{{ level.objective || '围绕该关卡能力目标展开训练' }}</p>
              </div>
            </div>

            <div class="plan-section-list">
              <div v-for="section in level.sections" :key="`${level.id}-${section.section_index}`" class="plan-section-item">
                <div class="plan-section-title">{{ section.title }}</div>
                <div class="plan-class-list">
                  <div
                    v-for="item in section.classes"
                    :key="item.id"
                    class="plan-unit-item"
                    :class="item.is_completed ? 'plan-unit-item--completed' : 'plan-unit-item--pending'"
                  >
                    <div class="plan-unit-index">{{ item.class_index }}</div>
                    <div class="plan-unit-body">
                      <div class="plan-unit-title-row">
                        <div class="plan-unit-title">{{ item.title }}</div>
                        <el-tag v-if="item.is_completed" type="success" effect="plain" size="small">已完成</el-tag>
                        <el-tag v-else type="info" effect="plain" size="small">未完成</el-tag>
                      </div>
                      <div class="plan-unit-desc">{{ item.description || '该课用于巩固本 section 的关键能力。' }}</div>
                      <div class="plan-unit-actions">
                        <span v-if="item.last_assessment_score !== null" class="plan-unit-score">最近得分：{{ Math.round((item.last_assessment_score || 0) * 100) }}%</span>
                      </div>
                    </div>
                    <el-button
                      v-if="!item.is_completed"
                      class="plan-jump-btn"
                      size="small"
                      type="primary"
                      round
                      :loading="assessmentLoading && assessmentClass?.id === item.id"
                      @click="openClassAssessment(item)"
                    >
                      跳到这里
                    </el-button>
                  </div>
                </div>
              </div>
            </div>
          </el-card>
        </div>
      </template>

      <el-empty v-else description="你还没有激活学习计划，请先创建一个计划" />
    </el-card>

    <el-dialog v-model="questionnaireVisible" title="创建学习计划" width="560px">
      <el-form label-position="top">
        <el-form-item label="学习语言">
          <el-select v-model="selectedNewLanguage" style="width: 100%">
            <el-option v-for="lang in languageChoices" :key="lang.code" :label="lang.label" :value="lang.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="当前掌握程度">
          <el-select v-model="questionnaire.current_level" style="width: 100%">
            <el-option
              v-for="item in currentLevelOptions"
              :key="`current-${item.value}`"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="目前掌握情况（简短自评）">
          <el-input v-model="questionnaire.self_assessment" type="textarea" :rows="3" placeholder="例如：会基础词汇和简单句，听力较弱，口语不流畅" />
        </el-form-item>
        <el-form-item label="目标水平">
          <el-select v-model="questionnaire.target_level" style="width: 100%">
            <el-option
              v-for="item in targetLevelOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="希望用多长时间达到目标（周）">
          <el-input-number v-model="questionnaire.target_duration_weeks" :min="1" :max="260" :step="1" />
        </el-form-item>
        <el-form-item label="过往学习经历（可选）">
          <el-input v-model="questionnaire.learning_experience" placeholder="例如：学过半年，停了一年" />
        </el-form-item>
        <el-form-item label="偏好重点（可选）">
          <el-input v-model="questionnaire.preferred_focus" placeholder="例如：口语、听力、商务写作" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="questionnaireVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreatePlan">创建计划</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="assessmentDialogVisible" :title="assessmentClass ? `Class测评：${assessmentClass.title}` : 'Class测评'" width="680px">
      <div v-if="assessmentStarting" class="plan-assessment-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>出题中，请稍候...</span>
      </div>
      <div v-else-if="!assessmentCurrentQuestion" class="plan-assessment-empty">暂无题目</div>
      <div v-else class="plan-assessment-question">
        <div class="plan-assessment-qtitle">第 {{ assessmentQuestionIndex }}/{{ assessmentTotalQuestions }} 题：{{ assessmentCurrentQuestion.prompt }}</div>
        <template v-if="assessmentCurrentQuestion.type === 'choice'">
          <el-radio-group v-model="assessmentCurrentAnswer">
            <el-radio v-for="(opt, oIdx) in assessmentCurrentQuestion.options || []" :key="oIdx" :value="letterLabel(oIdx)">
              {{ letterLabel(oIdx) }}. {{ opt }}
            </el-radio>
          </el-radio-group>
        </template>
        <template v-else-if="assessmentCurrentQuestion.type === 'judge'">
          <el-radio-group v-model="assessmentCurrentAnswer">
            <el-radio value="true">true</el-radio>
            <el-radio value="false">false</el-radio>
          </el-radio-group>
        </template>
        <template v-else>
          <el-input v-model="assessmentCurrentAnswer" placeholder="请输入答案" />
        </template>
      </div>
      <div v-if="assessmentHistory.length" class="plan-assessment-history">
        <div class="plan-assessment-history-title">已作答</div>
        <div v-for="(item, idx) in assessmentHistory" :key="idx" class="plan-assessment-history-item">
          {{ idx + 1 }}. {{ item.question.prompt }} → {{ item.answer }}
        </div>
      </div>
      <template #footer>
        <el-button @click="assessmentDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="assessmentStarting || !assessmentCurrentQuestion" :loading="assessmentSubmitting" @click="submitClassAssessment">
          {{ assessmentQuestionIndex >= assessmentTotalQuestions ? '提交并判定' : '下一题' }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>
