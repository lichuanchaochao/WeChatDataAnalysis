export const usePlanWindow = () => {
  const open = ref(false)
  const reason = ref('manual')
  const openPlanWindow = () => {}
  const closePlanWindow = () => {}
  return { open, reason, openPlanWindow, closePlanWindow }
}
