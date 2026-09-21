import { effectScope, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useChatExport } from '~/composables/chat/useChatExport'

vi.mock('~/lib/server-error-logging', () => ({ reportServerErrorFromResponse: vi.fn() }))

const scopes = []
const oldClient = process.client
const oldDesktop = window.wechatDesktop
afterEach(() => {
  scopes.splice(0).forEach(scope => scope.stop())
  process.client = oldClient
  window.wechatDesktop = oldDesktop
})

function setup(privacy = false) {
  process.client = true
  window.wechatDesktop = { chooseDirectory: vi.fn() }
  const api = { createChatExport: vi.fn().mockResolvedValue({ job: null }) }
  const scope = effectScope()
  scopes.push(scope)
  const state = scope.run(() => useChatExport({
    api, apiBase: 'http://127.0.0.1/api', contacts: ref([]),
    selectedAccount: ref('account'), selectedContact: ref({ username: 'friend' }),
    privacyMode: ref(privacy),
  }))
  state.exportSelectedUsernames.value = ['friend']
  state.exportFolder.value = 'C:\\test-only-output'
  state.exportMessageTypes.value = ['image']
  return { state, api }
}

describe('existing image upgrade request', () => {
  it('rechecks selected conversations without resetting the baseline', async () => {
    const { state, api } = setup()
    expect(state.exportRecheckImages.value).toBe(false)
    state.exportOutputMode.value = 'folder'
    state.exportRecheckImages.value = true
    await state.startChatExport()
    expect(state.exportError.value).toBe('')
    expect(api.createChatExport).toHaveBeenCalledWith(expect.objectContaining({
      usernames: ['friend'], recheck_media: true, reset_baseline: false,
      include_media: true, media_kinds: ['image'],
    }))
  })

  it.each(['zip', 'privacy'])('does not enable incremental image recheck for %s', async mode => {
    const { state, api } = setup(mode === 'privacy')
    state.exportOutputMode.value = mode === 'zip' ? 'zip' : 'folder'
    state.exportRecheckImages.value = true
    await state.startChatExport()
    expect(api.createChatExport).toHaveBeenCalledWith(expect.objectContaining({ recheck_media: false }))
  })
})
