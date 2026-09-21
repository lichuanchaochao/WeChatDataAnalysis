import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ref, computed } from 'vue'

describe('朋友圈图片全屏预览键盘导航 (ArrowLeft / ArrowRight / ArrowUp / ArrowDown)', () => {
  let posts
  let previewCtx
  let previewIsVideo
  let keydownHandler

  beforeEach(() => {
    posts = ref([])
    previewCtx = ref(null)
    previewIsVideo = computed(() => {
      const ctx = previewCtx.value
      if (!ctx) return false
      return Number(ctx.media?.type || 0) === 6
    })

    const snsPreviewImageItems = computed(() => {
      const items = []
      const list = Array.isArray(posts.value) ? posts.value : []
      for (let pIdx = 0; pIdx < list.length; pIdx++) {
        const post = list[pIdx]
        const mediaList = Array.isArray(post?.media) ? post.media : []
        for (let mIdx = 0; mIdx < mediaList.length; mIdx++) {
          const m = mediaList[mIdx]
          if (!m) continue
          if (Number(m.type || 0) === 6) continue
          items.push({
            post,
            media: m,
            idx: mIdx
          })
        }
      }
      return items
    })

    const currentSnsPreviewIndex = computed(() => {
      const ctx = previewCtx.value
      if (!ctx || previewIsVideo.value) return -1
      const items = snsPreviewImageItems.value
      if (!items.length) return -1

      const curPostId = String(ctx.post?.id || ctx.post?.tid || '')
      const curIdx = Number(ctx.idx ?? 0)

      let found = items.findIndex((it) => {
        const itPostId = String(it.post?.id || it.post?.tid || '')
        return itPostId === curPostId && it.idx === curIdx
      })
      if (found !== -1) return found

      found = items.findIndex((it) => it.post === ctx.post && it.idx === curIdx)
      if (found !== -1) return found

      const curMediaId = String(ctx.media?.id || '')
      const curUrl = String(ctx.media?.url || '')
      if (curMediaId || curUrl) {
        found = items.findIndex((it) => {
          if (curMediaId && String(it.media?.id || '') === curMediaId) return true
          if (curUrl && String(it.media?.url || '') === curUrl) return true
          return false
        })
        if (found !== -1) return found
      }

      return -1
    })

    const canSwitchSnsPreviewImage = computed(() => {
      if (previewIsVideo.value) return false
      return snsPreviewImageItems.value.length > 1 && currentSnsPreviewIndex.value !== -1
    })

    const snsPreviewCounterText = computed(() => {
      const total = snsPreviewImageItems.value.length
      const cur = currentSnsPreviewIndex.value
      if (total <= 1 || cur < 0) return ''
      return `${cur + 1} / ${total}`
    })

    const switchSnsPreviewImage = (direction) => {
      if (previewIsVideo.value) return
      const items = snsPreviewImageItems.value
      if (!items.length || items.length <= 1) return

      const curIdx = currentSnsPreviewIndex.value
      if (curIdx < 0) return

      const step = Number(direction || 0) < 0 ? -1 : 1
      const nextIdx = (curIdx + step + items.length) % items.length
      const target = items[nextIdx]
      if (!target) return

      previewCtx.value = { post: target.post, media: target.media, idx: target.idx }
    }

    const showPrevSnsPreviewImage = () => switchSnsPreviewImage(-1)
    const showNextSnsPreviewImage = () => switchSnsPreviewImage(1)
    const closeImagePreview = () => {
      previewCtx.value = null
    }

    keydownHandler = (e) => {
      const key = String(e?.key || '')

      if (previewCtx.value && !previewIsVideo.value) {
        if (key === 'ArrowLeft' || key === 'ArrowUp') {
          e.preventDefault?.()
          showPrevSnsPreviewImage()
          return
        }
        if (key === 'ArrowRight' || key === 'ArrowDown') {
          e.preventDefault?.()
          showNextSnsPreviewImage()
          return
        }
      }

      if (key === 'Escape') {
        if (previewCtx.value) {
          closeImagePreview()
        }
      }
    }

    // Expose helpers for test assertions
    return {
      snsPreviewImageItems,
      currentSnsPreviewIndex,
      canSwitchSnsPreviewImage,
      snsPreviewCounterText,
      showPrevSnsPreviewImage,
      showNextSnsPreviewImage,
      closeImagePreview
    }
  })

  it('跨帖子图片扁平化提取，并过滤纯视频媒体', () => {
    posts.value = [
      {
        id: 'post_1',
        displayName: '张三',
        media: [
          { id: 'm1_0', type: 2, url: 'http://example.com/p1_0.jpg' },
          { id: 'm1_1', type: 2, url: 'http://example.com/p1_1.jpg' }
        ]
      },
      {
        id: 'post_2',
        displayName: '李四',
        media: [
          { id: 'm2_v', type: 6, url: 'http://example.com/video.mp4' }, // 视频应过滤
          { id: 'm2_1', type: 2, url: 'http://example.com/p2_1.jpg' }
        ]
      },
      {
        id: 'post_3',
        displayName: '王五',
        media: [
          { id: 'm3_0', type: 2, url: 'http://example.com/p3_0.jpg' }
        ]
      }
    ]

    // 打开 post_1 的第一张图
    previewCtx.value = { post: posts.value[0], media: posts.value[0].media[0], idx: 0 }

    const rightEvent = { key: 'ArrowRight', preventDefault: vi.fn() }
    keydownHandler(rightEvent)
    expect(rightEvent.preventDefault).toHaveBeenCalled()
    // 切换到 post_1 的第二张图
    expect(previewCtx.value.media.id).toBe('m1_1')

    // 再次按 ArrowDown，跨帖切换到 post_2 的图片（跳过视频）
    const downEvent = { key: 'ArrowDown', preventDefault: vi.fn() }
    keydownHandler(downEvent)
    expect(previewCtx.value.media.id).toBe('m2_1')
    expect(previewCtx.value.post.id).toBe('post_2')

    // 再次按 ArrowRight，跨帖切换到 post_3 的图片
    keydownHandler({ key: 'ArrowRight', preventDefault: vi.fn() })
    expect(previewCtx.value.media.id).toBe('m3_0')
    expect(previewCtx.value.post.id).toBe('post_3')

    // 再次按 ArrowRight，循环回到第一张图
    keydownHandler({ key: 'ArrowRight', preventDefault: vi.fn() })
    expect(previewCtx.value.media.id).toBe('m1_0')
    expect(previewCtx.value.post.id).toBe('post_1')

    // 按 ArrowLeft，循环倒退到最后一张（post_3）
    const leftEvent = { key: 'ArrowLeft', preventDefault: vi.fn() }
    keydownHandler(leftEvent)
    expect(leftEvent.preventDefault).toHaveBeenCalled()
    expect(previewCtx.value.media.id).toBe('m3_0')

    // 按 ArrowUp，倒退到倒数第二张（post_2）
    const upEvent = { key: 'ArrowUp', preventDefault: vi.fn() }
    keydownHandler(upEvent)
    expect(upEvent.preventDefault).toHaveBeenCalled()
    expect(previewCtx.value.media.id).toBe('m2_1')
  })

  it('视频全屏预览时，方向键不拦截（交由原生播放器快进快退），按 Escape 正常退出', () => {
    posts.value = [
      {
        id: 'post_video',
        displayName: '张三',
        media: [
          { id: 'vid_1', type: 6, url: 'http://example.com/video.mp4' }
        ]
      }
    ]

    previewCtx.value = { post: posts.value[0], media: posts.value[0].media[0], idx: 0 }
    expect(previewIsVideo.value).toBe(true)

    const rightEvent = { key: 'ArrowRight', preventDefault: vi.fn() }
    keydownHandler(rightEvent)
    // 方向键未被 preventDefault，留给视频播放器快进
    expect(rightEvent.preventDefault).not.toHaveBeenCalled()

    // 按 Escape 退出全屏视频
    keydownHandler({ key: 'Escape' })
    expect(previewCtx.value).toBeNull()
  })
})
