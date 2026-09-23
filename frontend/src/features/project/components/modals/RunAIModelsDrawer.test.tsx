import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { APP_OVERLAY_ROOT_ID } from "@/providers/StageOverlayContext"
import { modelsApi } from "@/api/endpoints/models"
import { RunAIModelsDrawer } from "./RunAIModelsDrawer"

vi.mock("@/api/endpoints/models", () => ({
    modelsApi: {
        getModels: vi.fn(),
    },
}))

function addOverlayRoot() {
    let overlay = document.getElementById(APP_OVERLAY_ROOT_ID)
    if (!overlay) {
        overlay = document.createElement("div")
        overlay.id = APP_OVERLAY_ROOT_ID
        document.body.append(overlay)
    }
    return overlay
}

describe("RunAIModelsDrawer", () => {
    beforeEach(() => {
        vi.clearAllMocks()
        addOverlayRoot()
    })

    it("renders AI model names and versions, including BatDetect2", async () => {
        vi.mocked(modelsApi.getModels).mockResolvedValue({
            code: 0,
            message: "success",
            data: [
                {
                    model_id: 1,
                    name: "BirdNET-Analyzer",
                    version: "2.4",
                    description: "Bird identification",
                    source_url: null,
                    parameter: null,
                },
                {
                    model_id: 2,
                    name: "batdetect2",
                    version: "1.3.0",
                    description: "Bat detection",
                    source_url: null,
                    parameter: null,
                },
                {
                    model_id: 3,
                    name: "insects-base-cnn10-96k-t",
                    version: "1.0.0",
                    description: "Insects detection",
                    source_url: null,
                    parameter: null,
                },
            ],
        })

        render(
            <MemoryRouter>
                <RunAIModelsDrawer
                    open
                    mediaId={1}
                    projectId={10}
                    onClose={vi.fn()}
                />
            </MemoryRouter>,
        )

        // Verify model names
        expect(screen.getByText("BirdNET")).toBeInTheDocument()
        expect(screen.getByText("BatDetect2")).toBeInTheDocument()
        expect(screen.getByText("Insects")).toBeInTheDocument()

        // Wait for versions to be populated
        await waitFor(() => {
            expect(screen.getByText("v2.4")).toBeInTheDocument()
            expect(screen.getByText("v1.3.0")).toBeInTheDocument()
            expect(screen.getByText("v1.0.0")).toBeInTheDocument()
        })

        const drawer = document.querySelector(".ai-models-drawer")
        expect(drawer?.querySelector(".ant-drawer-footer")).not.toBeNull()
        expect(drawer?.querySelector(".ant-drawer-header .ant-drawer-extra")).toBeNull()
        expect(screen.getByRole("button", { name: "Run" })).toBeInTheDocument()
        expect(screen.getByText("AI Models")).toBeInTheDocument()
    })
})
