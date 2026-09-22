import { describe, it, expect } from 'vitest'

describe('antirecall page logic', () => {
  it('correctly filters sessions by search keyword and installed status', () => {
    const sessions = [
      { username: 'wxid_user1', displayName: '张三', installed: true, isChatroom: false },
      { username: '123456@chatroom', displayName: '交流群A', installed: false, isChatroom: true },
      { username: 'wxid_user2', displayName: '李四', installed: false, isChatroom: false },
      { username: '789101@chatroom', displayName: '工作群B', installed: true, isChatroom: true },
    ]

    // 1. All filter
    const filterAll = (kw) => sessions.filter(s => {
      if (!kw) return true
      return s.displayName.toLowerCase().includes(kw) || s.username.toLowerCase().includes(kw)
    })
    expect(filterAll('').length).toBe(4)
    expect(filterAll('张三').length).toBe(1)
    expect(filterAll('chatroom').length).toBe(2)

    // 2. Installed filter
    const filterInstalled = (kw) => sessions.filter(s => {
      if (!s.installed) return false
      if (!kw) return true
      return s.displayName.toLowerCase().includes(kw) || s.username.toLowerCase().includes(kw)
    })
    expect(filterInstalled('').length).toBe(2)
    expect(filterInstalled('工作').length).toBe(1)
    expect(filterInstalled('李四').length).toBe(0)

    // 3. Uninstalled filter
    const filterUninstalled = (kw) => sessions.filter(s => {
      if (s.installed) return false
      if (!kw) return true
      return s.displayName.toLowerCase().includes(kw) || s.username.toLowerCase().includes(kw)
    })
    expect(filterUninstalled('').length).toBe(2)
    expect(filterUninstalled('交流').length).toBe(1)
  })

  it('correctly detects intercepted anti-revoke system notices', () => {
    const isAntiRevokeNotice = (content) => {
      const text = String(content || '')
      return text.includes('尝试撤回此消息') || text.includes('撤回了')
    }

    expect(isAntiRevokeNotice('对方尝试撤回此消息')).toBe(true)
    expect(isAntiRevokeNotice('张三 尝试撤回此消息')).toBe(true)
    expect(isAntiRevokeNotice('李四撤回了一条消息')).toBe(true)
    expect(isAntiRevokeNotice('你撤回了一条消息')).toBe(true)
    expect(isAntiRevokeNotice('李四撤回了一条成员消息')).toBe(true)
    expect(isAntiRevokeNotice('早上好，今天开会')).toBe(false)
    expect(isAntiRevokeNotice('')).toBe(false)
    expect(isAntiRevokeNotice(null)).toBe(false)
  })
})
