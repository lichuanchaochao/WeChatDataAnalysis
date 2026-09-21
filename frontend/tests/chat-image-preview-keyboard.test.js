import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'

describe('聊天图片预览键盘导航 (ArrowLeft / ArrowRight / ArrowUp / ArrowDown)', () => {
  let previewImageUrl
  let previewImageItems
  let previewImageIndex
  let keydownHandler

  const switchPreviewImage = (direction) => {
    const list = previewImageItems.value
    if (!Array.isArray(list) || list.length <= 1) return
    const current = Number(previewImageIndex.value || 0)
    const step = Number(direction || 0) < 0 ? -1 : 1
    const next = (current + step + list.length) % list.length
    previewImageIndex.value = next
    previewImageUrl.value = String(list[next]?.url || '') || null
  }

  const showPrevPreviewImage = () => switchPreviewImage(-1)
  const showNextPreviewImage = () => switchPreviewImage(1)
  const closeImagePreview = () => {
    previewImageUrl.value = null
    previewImageItems.value = []
    previewImageIndex.value = -1
  }

  beforeEach(() => {
    previewImageUrl = ref(null)
    previewImageItems = ref([])
    previewImageIndex = ref(-1)

    keydownHandler = (event) => {
      const key = String(event?.key || '')
      if (previewImageUrl.value) {
        if (key === 'ArrowLeft' || key === 'ArrowUp') {
          event.preventDefault()
          showPrevPreviewImage()
          return
        }
        if (key === 'ArrowRight' || key === 'ArrowDown') {
          event.preventDefault()
          showNextPreviewImage()
          return
        }
      }
      if (key === 'Escape') {
        if (previewImageUrl.value) closeImagePreview()
      }
    }
  })

  it('多张图片预览时，方向键右/下切换到下一张，方向键左/上切换到上一张', () => {
    previewImageItems.value = [
      { id: '1', url: 'http://localhost/image1.jpg' },
      { id: '2', url: 'http://localhost/image2.jpg' },
      { id: '3', url: 'http://localhost/image3.jpg' }
    ]
    previewImageIndex.value = 0
    previewImageUrl.value = previewImageItems.value[0].url

    // 初始停留在第一张图
    expect(previewImageIndex.value).toBe(0)
    expect(previewImageUrl.value).toBe('http://localhost/image1.jpg')

    // 按 ArrowRight 切换到第二张
    const rightEvent = { key: 'ArrowRight', preventDefault: vi.fn() }
    keydownHandler(rightEvent)
    expect(rightEvent.preventDefault).toHaveBeenCalled()
    expect(previewImageIndex.value).toBe(1)
    expect(previewImageUrl.value).toBe('http://localhost/image2.jpg')

    // 按 ArrowDown 切换到第三张
    const downEvent = { key: 'ArrowDown', preventDefault: vi.fn() }
    keydownHandler(downEvent)
    expect(downEvent.preventDefault).toHaveBeenCalled()
    expect(previewImageIndex.value).toBe(2)
    expect(previewImageUrl.value).toBe('http://localhost/image3.jpg')

    // 再次按 ArrowRight，循环回到第一张
    keydownHandler({ key: 'ArrowRight', preventDefault: vi.fn() })
    expect(previewImageIndex.value).toBe(0)
    expect(previewImageUrl.value).toBe('http://localhost/image1.jpg')

    // 按 ArrowLeft，循环退到最后一张（第三张）
    const leftEvent = { key: 'ArrowLeft', preventDefault: vi.fn() }
    keydownHandler(leftEvent)
    expect(leftEvent.preventDefault).toHaveBeenCalled()
    expect(previewImageIndex.value).toBe(2)
    expect(previewImageUrl.value).toBe('http://localhost/image3.jpg')

    // 按 ArrowUp 退回到第二张
    const upEvent = { key: 'ArrowUp', preventDefault: vi.fn() }
    keydownHandler(upEvent)
    expect(upEvent.preventDefault).toHaveBeenCalled()
    expect(previewImageIndex.value).toBe(1)
    expect(previewImageUrl.value).toBe('http://localhost/image2.jpg')
  })

  it('按 Escape 关闭预览，关闭后按方向键不触发切换', () => {
    previewImageItems.value = [
      { id: '1', url: 'http://localhost/image1.jpg' },
      { id: '2', url: 'http://localhost/image2.jpg' }
    ]
    previewImageIndex.value = 0
    previewImageUrl.value = previewImageItems.value[0].url

    // 按 Escape
    const escEvent = { key: 'Escape', preventDefault: vi.fn() }
    keydownHandler(escEvent)
    expect(previewImageUrl.value).toBeNull()
    expect(previewImageIndex.value).toBe(-1)

    // 预览已关闭，按方向键不应发生变化
    const rightEvent = { key: 'ArrowRight', preventDefault: vi.fn() }
    keydownHandler(rightEvent)
    expect(rightEvent.preventDefault).not.toHaveBeenCalled()
    expect(previewImageUrl.value).toBeNull()
  })
})
