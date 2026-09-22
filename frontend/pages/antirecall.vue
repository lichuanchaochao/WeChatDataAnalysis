<template>
  <div class="antirecall-page theme-scope h-screen flex flex-col overflow-hidden" style="background-color: var(--app-shell-bg)">
    <!-- Header -->
    <div class="flex-shrink-0 px-6 pt-5 pb-2">
      <h1 class="text-[24px] font-bold tracking-tight text-[#111827] dark:text-[#f3f4f6]">防撤回</h1>
      <p class="text-[12px] text-gray-500 dark:text-gray-400 mt-0.5">防撤回触发与已撤回消息</p>
    </div>

    <!-- Main Content Area -->
    <div class="flex-1 min-h-0 flex flex-col px-6 pb-6 gap-3 overflow-hidden">
      <!-- Top Card: Status -->
      <section class="flex-shrink-0 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-[#1b1e22] p-4 shadow-sm">
        <div class="flex items-center justify-between gap-4">
          <div class="flex items-center gap-3 min-w-0">
            <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-500/10 text-blue-600 dark:bg-blue-500/20 dark:text-blue-400">
              <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <path d="m9 12 2 2 4-4" />
              </svg>
            </div>
            <div class="min-w-0">
              <div class="text-[15px] font-semibold text-gray-900 dark:text-gray-100">
                <template v-if="loading && !sessions.length">正在读取会话与触发器状态...</template>
                <template v-else>已安装 {{ installedCount }} / {{ totalCount }} 个会话</template>
              </div>
              <div class="text-[12px] text-gray-500 dark:text-gray-400 mt-0.5">
                触发器常在微信端，装好后不必保持本软件运行
              </div>
            </div>
          </div>

          <button
            type="button"
            class="flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/80 px-3 py-1.5 text-[12px] font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700 transition disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
            :disabled="busy || !selectedAccount"
            @click="refreshData(true)"
          >
            <svg class="h-3.5 w-3.5" :class="{ 'animate-spin': busy }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
              <path d="M3 3v5h5" />
              <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
              <path d="M16 21h5v-5" />
            </svg>
            <span>{{ busy ? '处理中…' : '刷新状态' }}</span>
          </button>
        </div>

        <div class="mt-3 border-t border-gray-100 dark:border-gray-800/70 pt-2.5 text-[11px] leading-relaxed text-gray-400 dark:text-gray-500">
          对选中的会话安装防撤回触发器后，对方撤回的消息在微信本体仍会保留可见。安装/卸载针对具体会话，微信升级后一般无需重复。
        </div>
      </section>

      <!-- Middle Card: Sessions List -->
      <section class="flex-1 min-h-0 flex flex-col rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-[#1b1e22] shadow-sm overflow-hidden">
        <!-- Panel Header -->
        <div class="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 dark:border-gray-800 px-4 py-3">
          <div class="flex items-center gap-2">
            <svg class="h-4 w-4 text-blue-600 dark:text-blue-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              <path d="m9 12 2 2 4-4" />
            </svg>
            <h2 class="text-[14px] font-semibold text-gray-900 dark:text-gray-100">会话</h2>
          </div>

          <div class="flex items-center gap-2.5">
            <!-- Search -->
            <div class="relative w-48 sm:w-60">
              <svg class="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="11" cy="11" r="8" />
                <path d="m21 21-4.3-4.3" />
              </svg>
              <input
                v-model="searchQuery"
                type="text"
                placeholder="搜索会话…"
                class="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50/70 dark:bg-gray-800/60 py-1.5 pl-8 pr-7 text-[12px] text-gray-800 dark:text-gray-100 outline-none transition placeholder:text-gray-400 focus:border-blue-500 focus:bg-white dark:focus:bg-[#1b1e22]"
              />
              <button
                v-if="searchQuery"
                type="button"
                class="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
                @click="searchQuery = ''"
              >
                <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M18 6 6 18M6 6l12 12" />
                </svg>
              </button>
            </div>

            <!-- Segmented Filter -->
            <div class="flex rounded-lg bg-gray-100 dark:bg-gray-800 p-0.5 text-[12px]">
              <button
                v-for="tab in filterTabs"
                :key="tab.id"
                type="button"
                class="rounded-md px-2.5 py-1 font-medium transition"
                :class="currentFilter === tab.id
                  ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-xs'
                  : 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200'"
                @click="currentFilter = tab.id"
              >
                {{ tab.label }}
              </button>
            </div>
          </div>
        </div>

        <!-- Panel Subheader / Actions -->
        <div class="flex items-center justify-between border-b border-gray-100 dark:border-gray-800/80 bg-gray-50/50 dark:bg-gray-900/30 px-4 py-2 text-[12px]">
          <span class="text-gray-500 dark:text-gray-400">
            当前显示 {{ filteredSessions.length }} / {{ totalCount }} 个会话
          </span>

          <div class="flex items-center gap-2">
            <button
              type="button"
              class="flex items-center gap-1 rounded-md bg-blue-600 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
              :disabled="busy || !uninstalledSessionIds.length"
              @click="installBatch(uninstalledSessionIds)"
            >
              <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <path d="M12 8v8M8 12h8" />
              </svg>
              <span>全部安装</span>
            </button>

            <button
              type="button"
              class="flex items-center gap-1 rounded-md border border-red-200 dark:border-red-900/60 bg-red-50 dark:bg-red-950/40 px-2.5 py-1 text-[11px] font-medium text-red-600 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/60 disabled:opacity-50 disabled:cursor-not-allowed transition"
              :disabled="busy || !installedSessionIds.length"
              @click="uninstallBatch(installedSessionIds)"
            >
              <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                <path d="M3 3v5h5" />
              </svg>
              <span>全部还原</span>
            </button>
          </div>
        </div>

        <!-- Session List -->
        <div class="flex-1 min-h-0 overflow-y-auto divide-y divide-gray-100 dark:divide-gray-800/40 p-1">
          <div v-if="loading && !sessions.length" class="flex flex-col items-center justify-center py-16 text-gray-400">
            <svg class="h-6 w-6 animate-spin text-blue-500 mb-2" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10" stroke-opacity="0.25" />
              <path d="M12 2a10 10 0 0 1 10 10" />
            </svg>
            <div class="text-[13px]">正在读取会话与触发器状态…</div>
          </div>

          <div v-else-if="!filteredSessions.length" class="flex flex-col items-center justify-center py-16 text-gray-400">
            <div class="text-[13px]">没有符合当前筛选的会话</div>
          </div>

          <div
            v-for="s in filteredSessions"
            :key="s.username"
            class="flex items-center gap-3 px-3 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-800/40 transition rounded-md group"
            style="content-visibility: auto; contain-intrinsic-size: 0 32px;"
          >
            <!-- Avatar -->
            <div
              class="h-6 w-6 shrink-0 overflow-hidden bg-gray-200 dark:bg-gray-700"
              :class="[
                s.isChatroom ? 'rounded' : 'rounded-full',
                { 'privacy-blur': privacyMode }
              ]"
            >
              <img
                v-if="s.avatarUrl && !brokenAvatars[s.username]"
                :src="s.avatarUrl"
                :alt="s.displayName"
                class="h-full w-full object-cover"
                loading="lazy"
                referrerpolicy="no-referrer"
                @error="brokenAvatars[s.username] = true"
              />
              <div
                v-else
                class="flex h-full w-full items-center justify-center text-[10px] font-semibold text-white"
                :class="s.isChatroom ? 'bg-emerald-600' : 'bg-gray-500'"
              >
                {{ s.isChatroom ? '群' : (s.displayName ? s.displayName.slice(0, 1) : '人') }}
              </div>
            </div>

            <!-- Name & Info -->
            <div class="min-w-0 flex-[0_1_45%] flex items-center gap-1.5" :class="{ 'privacy-blur': privacyMode }">
              <span class="truncate text-[12px] font-medium text-gray-900 dark:text-gray-100" :title="s.displayName">
                {{ s.displayName }}
              </span>
              <span
                v-if="s.isChatroom"
                class="shrink-0 rounded bg-gray-100 dark:bg-gray-800 px-1 py-0.2 text-[9px] text-gray-500 dark:text-gray-400"
              >
                群聊
              </span>
            </div>

            <!-- Username / wxid -->
            <div class="min-w-0 flex-1 truncate font-mono text-[11px] text-gray-400 dark:text-gray-500" :class="{ 'privacy-blur': privacyMode }">
              {{ s.username }}
            </div>

            <!-- Action Button -->
            <div class="shrink-0">
              <button
                type="button"
                class="rounded px-2.5 py-0.5 text-[11px] font-medium transition disabled:opacity-50"
                :class="s.installed
                  ? 'border border-gray-200 dark:border-gray-700 bg-transparent text-gray-600 dark:text-gray-400 hover:border-red-300 hover:text-red-600 dark:hover:border-red-800 dark:hover:text-red-400'
                  : 'border border-blue-500/30 bg-blue-50 text-blue-600 hover:bg-blue-600 hover:text-white dark:bg-blue-950/40 dark:text-blue-400 dark:border-blue-800 dark:hover:bg-blue-600 dark:hover:text-white'"
                :disabled="busy || operatingSession === s.username"
                @click="toggleSession(s)"
              >
                <span v-if="operatingSession === s.username">处理中…</span>
                <span v-else>{{ s.installed ? '还原' : '安装' }}</span>
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- Bottom Card: Auto & Batch Settings -->
      <section class="flex-shrink-0 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-[#1b1e22] p-4 shadow-sm">
        <div class="flex items-center gap-2 border-b border-gray-100 dark:border-gray-800 pb-2.5 mb-3">
          <svg class="h-4 w-4 text-blue-600 dark:text-blue-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
            <path d="M3 3v5h5" />
          </svg>
          <h3 class="text-[13px] font-semibold text-gray-900 dark:text-gray-100">自动与批量</h3>
        </div>

        <div class="flex items-center justify-between gap-4">
          <div class="flex items-start gap-3 min-w-0">
            <div class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-blue-500/10 text-blue-600 dark:bg-blue-500/20 dark:text-blue-400">
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <path d="M12 8v8M8 12h8" />
              </svg>
            </div>
            <div class="min-w-0">
              <div class="text-[13px] font-medium text-gray-900 dark:text-gray-100">新群聊自动安装</div>
              <div class="text-[11px] text-gray-400 dark:text-gray-500 mt-0.5">
                只处理开启后首次观察到的新群，会延迟排队，不影响消息通知
              </div>
            </div>
          </div>

          <!-- Switch -->
          <button
            type="button"
            role="switch"
            :aria-checked="autoApplyNewGroups"
            class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none disabled:opacity-50"
            :class="autoApplyNewGroups ? 'bg-blue-600' : 'bg-gray-200 dark:bg-gray-700'"
            :disabled="busy || configLoading"
            @click="toggleAutoApply"
          >
            <span
              aria-hidden="true"
              class="pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
              :class="autoApplyNewGroups ? 'translate-x-4' : 'translate-x-0'"
            />
          </button>
        </div>
      </section>
    </div>

    <!-- Floating Toast Notification -->
    <Transition name="toast">
      <div
        v-if="toast.visible"
        class="fixed bottom-6 right-6 z-50 flex items-center gap-2 rounded-lg px-4 py-2.5 text-[12px] font-medium shadow-lg transition-all"
        :class="toast.type === 'error'
          ? 'bg-red-600 text-white shadow-red-900/20'
          : 'bg-emerald-600 text-white shadow-emerald-900/20'"
      >
        <svg v-if="toast.type === 'error'" class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
        <svg v-else class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M20 6 9 17l-5-5" />
        </svg>
        <span>{{ toast.message }}</span>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { storeToRefs } from 'pinia'
import { useChatAccountsStore } from '~/stores/chatAccounts'
import { usePrivacyStore } from '~/stores/privacy'

useHead({ title: '防撤回 - 微信数据分析助手' })

const api = useApi()
const chatAccounts = useChatAccountsStore()
const { selectedAccount } = storeToRefs(chatAccounts)
const privacyStore = usePrivacyStore()
const { privacyMode } = storeToRefs(privacyStore)

const sessions = ref([])
const totalCount = ref(0)
const installedCount = ref(0)
const loading = ref(false)
const busy = ref(false)
const configLoading = ref(false)
const autoApplyNewGroups = ref(false)
const searchQuery = ref('')
const currentFilter = ref('all')
const brokenAvatars = reactive({})
const operatingSession = ref(null)

const toast = reactive({
  visible: false,
  message: '',
  type: 'success',
  timer: null
})

const showToast = (message, type = 'success') => {
  if (toast.timer) clearTimeout(toast.timer)
  toast.message = message
  toast.type = type
  toast.visible = true
  toast.timer = setTimeout(() => {
    toast.visible = false
  }, 3500)
}

const filterTabs = [
  { id: 'all', label: '全部' },
  { id: 'installed', label: '已安装' },
  { id: 'uninstalled', label: '未安装' },
]

const filteredSessions = computed(() => {
  const kw = searchQuery.value.trim().toLowerCase()
  return sessions.value.filter((s) => {
    if (currentFilter.value === 'installed' && !s.installed) return false
    if (currentFilter.value === 'uninstalled' && s.installed) return false
    if (!kw) return true
    return (s.displayName || '').toLowerCase().includes(kw) || s.username.toLowerCase().includes(kw)
  })
})

const installedSessionIds = computed(() => {
  return sessions.value.filter(s => s.installed).map(s => s.username)
})

const uninstalledSessionIds = computed(() => {
  return sessions.value.filter(s => !s.installed).map(s => s.username)
})

const refreshData = async (manual = false) => {
  if (!selectedAccount.value) {
    sessions.value = []
    totalCount.value = 0
    installedCount.value = 0
    return
  }

  loading.value = true
  if (manual) busy.value = true
  try {
    const [sessionsRes, configRes] = await Promise.all([
      api.getAntiRevokeSessions(selectedAccount.value),
      api.getAntiRevokeConfig(selectedAccount.value).catch(() => ({ antiRevokeAutoApplyNewGroups: false }))
    ])

    if (sessionsRes?.success) {
      sessions.value = Array.isArray(sessionsRes.sessions) ? sessionsRes.sessions : []
      totalCount.value = Number(sessionsRes.totalCount || sessions.value.length)
      installedCount.value = Number(sessionsRes.installedCount || sessions.value.filter(s => s.installed).length)
    }

    if (configRes && typeof configRes.antiRevokeAutoApplyNewGroups === 'boolean') {
      autoApplyNewGroups.value = configRes.antiRevokeAutoApplyNewGroups
    }

    if (manual) {
      showToast('防撤回状态已刷新')
    }
  } catch (err) {
    showToast(`刷新状态失败: ${err.message || err}`, 'error')
  } finally {
    loading.value = false
    if (manual) busy.value = false
  }
}

const toggleSession = async (session) => {
  if (busy.value || !selectedAccount.value) return
  operatingSession.value = session.username
  busy.value = true

  const willInstall = !session.installed
  try {
    const fn = willInstall ? api.installAntiRevokeTriggers : api.uninstallAntiRevokeTriggers
    const res = await fn(selectedAccount.value, [session.username])
    if (res?.success) {
      session.installed = willInstall
      installedCount.value = sessions.value.filter(s => s.installed).length
      showToast(willInstall ? `已为「${session.displayName}」安装防撤回` : `已还原「${session.displayName}」的防撤回`)
      await refreshData()
    } else {
      showToast(res?.error || '操作失败', 'error')
    }
  } catch (err) {
    showToast(`操作失败: ${err.message || err}`, 'error')
  } finally {
    operatingSession.value = null
    busy.value = false
  }
}

const installBatch = async (sessionIds) => {
  if (!sessionIds.length || busy.value || !selectedAccount.value) return
  busy.value = true
  try {
    const res = await api.installAntiRevokeTriggers(selectedAccount.value, sessionIds)
    if (res?.success) {
      const ok = res.rows?.filter(r => r.success).length || 0
      const failed = res.rows?.filter(r => !r.success).length || 0
      showToast(`防撤回安装完成，成功 ${ok}${failed ? ` / 失败 ${failed}` : ''}`)
      const successSet = new Set(
        res.rows?.filter(r => r.success).map(r => r.sessionId || r.session_id) || sessionIds
      )
      for (const s of sessions.value) {
        if (successSet.has(s.username)) {
          s.installed = true
        }
      }
      installedCount.value = sessions.value.filter(s => s.installed).length
      await refreshData()
    } else {
      showToast(res?.error || '批量安装失败', 'error')
    }
  } catch (err) {
    showToast(`批量安装失败: ${err.message || err}`, 'error')
  } finally {
    busy.value = false
  }
}

const uninstallBatch = async (sessionIds) => {
  if (!sessionIds.length || busy.value || !selectedAccount.value) return
  busy.value = true
  try {
    const res = await api.uninstallAntiRevokeTriggers(selectedAccount.value, sessionIds)
    if (res?.success) {
      const ok = res.rows?.filter(r => r.success).length || 0
      showToast(`防撤回已还原，成功 ${ok}`)
      const successSet = new Set(
        res.rows?.filter(r => r.success).map(r => r.sessionId || r.session_id) || sessionIds
      )
      for (const s of sessions.value) {
        if (successSet.has(s.username)) {
          s.installed = false
        }
      }
      installedCount.value = sessions.value.filter(s => s.installed).length
      await refreshData()
    } else {
      showToast(res?.error || '批量还原失败', 'error')
    }
  } catch (err) {
    showToast(`批量还原失败: ${err.message || err}`, 'error')
  } finally {
    busy.value = false
  }
}

const toggleAutoApply = async () => {
  if (!selectedAccount.value || configLoading.value) return
  const nextVal = !autoApplyNewGroups.value
  configLoading.value = true
  try {
    const res = await api.setAntiRevokeConfig(selectedAccount.value, nextVal)
    if (res?.success) {
      autoApplyNewGroups.value = nextVal
      showToast(nextVal ? '已开启新群聊自动防撤回' : '已关闭新群聊自动防撤回')
    } else {
      showToast('设置保存失败', 'error')
    }
  } catch (err) {
    showToast(`设置失败: ${err.message || err}`, 'error')
  } finally {
    configLoading.value = false
  }
}

watch(selectedAccount, () => {
  void refreshData()
})

onMounted(async () => {
  await chatAccounts.ensureLoaded()
  await refreshData()
})
</script>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(12px) scale(0.95);
}
</style>
