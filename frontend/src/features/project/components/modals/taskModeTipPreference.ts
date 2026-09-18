import { isFunctionalCookiesAllowed } from "../../../home/cookieConsent"

export const TASK_MODE_TIP_STORAGE_KEY = "ecoSignal_task_mode_tip_dismissed"

export function isTaskModeTipDismissed(): boolean {
    if (typeof window === "undefined") return false
    try {
        if (window.localStorage.getItem(TASK_MODE_TIP_STORAGE_KEY) === "1") return true
        if (window.sessionStorage.getItem(TASK_MODE_TIP_STORAGE_KEY) === "1") return true
    } catch {
        /* ignore */
    }
    return false
}

export function setTaskModeTipDismissed(dismissed: boolean): void {
    if (typeof window === "undefined") return
    const value = dismissed ? "1" : ""
    try {
        if (dismissed) {
            if (isFunctionalCookiesAllowed()) {
                window.localStorage.setItem(TASK_MODE_TIP_STORAGE_KEY, value)
            } else {
                window.sessionStorage.setItem(TASK_MODE_TIP_STORAGE_KEY, value)
            }
        } else {
            window.localStorage.removeItem(TASK_MODE_TIP_STORAGE_KEY)
            window.sessionStorage.removeItem(TASK_MODE_TIP_STORAGE_KEY)
        }
    } catch {
        /* ignore */
    }
}
