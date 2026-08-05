// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from "vitest"

import {
    AUTH_LOGIN_REQUIRED_EVENT,
    authUtils,
    dispatchLoginRequired,
    resetLoginRequiredDispatch,
} from "./auth"

describe("dispatchLoginRequired idempotency", () => {
    let authChangeCount = 0
    let loginRequiredCount = 0
    const onAuthChange = () => {
        authChangeCount += 1
    }
    const onLoginRequired = () => {
        loginRequiredCount += 1
    }

    beforeEach(() => {
        vi.clearAllMocks()
        localStorage.clear()
        resetLoginRequiredDispatch()
        authChangeCount = 0
        loginRequiredCount = 0
        window.removeEventListener("eco-auth-change", onAuthChange)
        window.removeEventListener(AUTH_LOGIN_REQUIRED_EVENT, onLoginRequired)
        window.addEventListener("eco-auth-change", onAuthChange)
        window.addEventListener(AUTH_LOGIN_REQUIRED_EVENT, onLoginRequired)
    })

    it("clears auth and dispatches both events once on first 401", () => {
        authUtils.setToken("token-a")
        authUtils.setUser("alice")

        dispatchLoginRequired()

        expect(authUtils.getToken()).toBeNull()
        expect(authUtils.getUser()).toBeNull()
        expect(authChangeCount).toBe(1)
        expect(loginRequiredCount).toBe(1)
    })

    it("does not re-dispatch events on repeated 401s", () => {
        authUtils.setToken("token-a")

        dispatchLoginRequired()
        dispatchLoginRequired()
        dispatchLoginRequired()

        expect(authChangeCount).toBe(1)
        expect(loginRequiredCount).toBe(1)
    })

    it("allows dispatch again after resetLoginRequiredDispatch", () => {
        authUtils.setToken("token-a")
        dispatchLoginRequired()

        resetLoginRequiredDispatch()
        authUtils.setToken("token-b")
        dispatchLoginRequired()

        expect(authChangeCount).toBe(2)
        expect(loginRequiredCount).toBe(2)
    })
})

describe("authUtils.clearAuth idempotency", () => {
    let authChangeCount = 0
    const onAuthChange = () => {
        authChangeCount += 1
    }

    beforeEach(() => {
        localStorage.clear()
        authChangeCount = 0
        window.removeEventListener("eco-auth-change", onAuthChange)
        window.addEventListener("eco-auth-change", onAuthChange)
    })

    it("broadcasts auth-change only when credentials were stored", () => {
        authUtils.setToken("token-a")

        authUtils.clearAuth()
        authUtils.clearAuth()

        expect(authChangeCount).toBe(1)
    })

    it("skips auth-change when nothing is stored", () => {
        authUtils.clearAuth()

        expect(authChangeCount).toBe(0)
    })
})
