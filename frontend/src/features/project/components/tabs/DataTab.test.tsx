import { act, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { MemoryRouter } from "react-router-dom"

import { usersApi } from "@/api/endpoints/users"
import { useProjectStore } from "../../stores/useProjectStore"
import { DataTab } from "./DataTab"

vi.mock("../data/pages/AudiosPage", () => ({ AudiosPage: () => <div>Audio table</div> }))
vi.mock("../data/pages/PhotosPage", () => ({ PhotosPage: () => <div>Photo table</div> }))

describe("DataTab", () => {
    afterEach(() => {
        vi.restoreAllMocks()
        act(() => {
            useProjectStore.setState({
                projects: [],
                currentProjectId: null,
                currentCollectionId: null,
            })
        })
    })

    it("shows the Media icon on the group and the soundwave on Audios", async () => {
        vi.spyOn(usersApi, "getMenuItems").mockResolvedValue({
            code: 0,
            message: "success",
            data: [
                { name: "Audios", visible: true },
                { name: "Photos", visible: true },
            ],
        })
        act(() => {
            useProjectStore.setState({
                projects: [{ id: 93739, name: "Project One" }],
                currentProjectId: 93739,
                currentCollectionId: "all",
            })
        })

        render(
            <MemoryRouter initialEntries={["/dashboard/93739?tab=data&dataNav=audio"]}>
                <DataTab />
            </MemoryRouter>,
        )

        const mediaGroup = await screen.findByRole("button", { name: "Media" })
        expect(mediaGroup.querySelector("svg circle")).not.toBeNull()
        expect(mediaGroup.querySelector("svg path")).not.toBeNull()
        const audioGroup = screen.getByRole("group", { name: "Media" })
        expect(within(audioGroup).getByRole("button", { name: "Audios" }).querySelector("svg.lucide-audio-lines")).not.toBeNull()
    })
})
