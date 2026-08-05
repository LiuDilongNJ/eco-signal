import "@testing-library/jest-dom"

if (typeof window.matchMedia !== "function") {
    Object.defineProperty(window, "matchMedia", {
        configurable: true,
        value: (query: string): MediaQueryList => ({
            matches: false,
            media: query,
            onchange: null,
            addListener: () => undefined,
            removeListener: () => undefined,
            addEventListener: () => undefined,
            removeEventListener: () => undefined,
            dispatchEvent: () => false,
        }),
    })
}

if (typeof globalThis.ResizeObserver !== "function") {
    class TestResizeObserver implements ResizeObserver {
        disconnect() {}
        observe() {}
        unobserve() {}
    }
    Object.defineProperty(globalThis, "ResizeObserver", {
        configurable: true,
        value: TestResizeObserver,
    })
}

const nativeGetComputedStyle = window.getComputedStyle.bind(window)
window.getComputedStyle = (element: Element, pseudoElement?: string | null) =>
    nativeGetComputedStyle(element, pseudoElement ? undefined : pseudoElement)

function createMemoryStorage(): Storage {
    const values = new Map<string, string>()
    return {
        get length() {
            return values.size
        },
        clear: () => values.clear(),
        getItem: (key) => values.get(key) ?? null,
        key: (index) => [...values.keys()][index] ?? null,
        removeItem: (key) => {
            values.delete(key)
        },
        setItem: (key, value) => {
            values.set(key, String(value))
        },
    }
}

if (typeof globalThis.localStorage?.clear !== "function") {
    const storage = createMemoryStorage()
    Object.defineProperty(globalThis, "localStorage", { configurable: true, value: storage })
    Object.defineProperty(window, "localStorage", { configurable: true, value: storage })
}
