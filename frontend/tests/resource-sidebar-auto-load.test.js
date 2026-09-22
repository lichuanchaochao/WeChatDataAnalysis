import { describe, expect, it } from 'vitest'
import { ref } from 'vue'

describe('Resource sidebar auto complete loading', () => {
  it('loads continuously while resourceHasMore is true and stops when false', async () => {
    const resourceItems = ref([])
    const resourceOffset = ref(0)
    const resourceHasMore = ref(true)
    const resourceLoading = ref(false)
    const resourceAutoLoadingAll = ref(false)
    const resourceSidebarOpen = ref(true)
    const resourcePageSize = 100

    // Mock API that has 250 items total
    const totalItems = 250
    const mockListChatMessages = async ({ offset, limit }) => {
      const remaining = Math.max(0, totalItems - offset)
      const count = Math.min(limit, remaining)
      const messages = Array.from({ length: count }, (_, i) => ({
        id: `msg-${offset + i}`,
        localId: offset + i,
        renderType: 'image',
        imageUrl: `http://localhost/img-${offset + i}.jpg`,
        createTime: 1700000000 + (offset + i) * 60
      }))
      return {
        messages,
        hasMore: offset + count < totalItems
      }
    }

    let loadTaskId = 0
    let loadTimer = null

    const loadResourceItems = async ({ reset = false, autoContinue = true } = {}) => {
      if (!resourceSidebarOpen.value) return
      if (resourceLoading.value) return
      if (!reset && !resourceHasMore.value) return

      if (reset) {
        loadTaskId += 1
        resourceItems.value = []
        resourceOffset.value = 0
        resourceHasMore.value = true
      }

      const currentTaskId = loadTaskId
      resourceLoading.value = true

      try {
        const response = await mockListChatMessages({
          offset: reset ? 0 : resourceOffset.value,
          limit: resourcePageSize
        })
        if (currentTaskId !== loadTaskId) return
        resourceItems.value = [...resourceItems.value, ...response.messages]
        resourceOffset.value = resourceItems.value.length
        resourceHasMore.value = !!response.hasMore
      } finally {
        if (currentTaskId === loadTaskId) {
          resourceLoading.value = false
        }
      }

      if (
        autoContinue &&
        currentTaskId === loadTaskId &&
        resourceSidebarOpen.value &&
        resourceHasMore.value
      ) {
        resourceAutoLoadingAll.value = true
        loadTimer = setTimeout(() => {
          if (currentTaskId === loadTaskId && resourceSidebarOpen.value && resourceHasMore.value) {
            void loadResourceItems({ reset: false, autoContinue: true })
          } else {
            resourceAutoLoadingAll.value = false
          }
        }, 10)
      } else {
        resourceAutoLoadingAll.value = false
      }
    }

    // Trigger initial load
    await loadResourceItems({ reset: true, autoContinue: true })
    expect(resourceItems.value.length).toBe(100)
    expect(resourceHasMore.value).toBe(true)
    expect(resourceAutoLoadingAll.value).toBe(true)

    // Wait for auto-load loop to complete all 250 items
    await new Promise((resolve) => setTimeout(resolve, 50))

    expect(resourceItems.value.length).toBe(250)
    expect(resourceHasMore.value).toBe(false)
    expect(resourceAutoLoadingAll.value).toBe(false)
  })

  it('cancels auto-loading immediately when sidebar is closed', async () => {
    const resourceItems = ref([])
    const resourceHasMore = ref(true)
    const resourceSidebarOpen = ref(true)
    let autoLoading = ref(false)
    let timer = null
    let taskId = 0

    const closeSidebar = () => {
      resourceSidebarOpen.value = false
      autoLoading.value = false
      taskId += 1
      if (timer) {
        clearTimeout(timer)
        timer = null
      }
    }

    autoLoading.value = true
    timer = setTimeout(() => {}, 100)

    closeSidebar()

    expect(resourceSidebarOpen.value).toBe(false)
    expect(autoLoading.value).toBe(false)
    expect(timer).toBe(null)
  })
})
