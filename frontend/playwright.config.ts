import { defineConfig, devices } from "@playwright/test"

export default defineConfig({
    testDir: "./e2e",
    outputDir: "./test-results/visual",
    snapshotPathTemplate: "{testDir}/__screenshots__/{projectName}/{arg}{ext}",
    fullyParallel: true,
    reporter: "list",
    use: {
        baseURL: "http://127.0.0.1:5173",
        channel: "chrome",
        colorScheme: "light",
        reducedMotion: "reduce",
    },
    webServer: {
        command: "npm run dev -- --host 127.0.0.1",
        url: "http://127.0.0.1:5173/e2e/fixtures/ui-contracts.html",
        reuseExistingServer: true,
        timeout: 120_000,
    },
    projects: [
        { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } },
        { name: "mobile", use: { ...devices["iPhone 13"], browserName: "chromium", channel: "chrome", viewport: { width: 390, height: 844 } } },
    ],
})
