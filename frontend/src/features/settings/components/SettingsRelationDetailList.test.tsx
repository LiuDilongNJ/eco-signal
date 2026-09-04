import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { SettingsRelationDetailList } from "./SettingsRelationDetailList"

describe("SettingsRelationDetailList", () => {
    it("renders names, fallback labels, and notes", () => {
        render(
            <SettingsRelationDetailList
                title="Linked Microphones"
                fallbackLabel="Microphone"
                emptyMessage="No microphones associated."
                isDark={false}
                items={[
                    { id: 1, name: "Microphone A", notes: "Primary microphone" },
                    { id: 2, name: null },
                ]}
            />,
        )

        expect(screen.getByText("Linked Microphones")).toBeInTheDocument()
        expect(screen.getByText("Microphone A")).toBeInTheDocument()
        expect(screen.getByText("Microphone #2")).toBeInTheDocument()
        expect(screen.getByText("Primary microphone")).toBeInTheDocument()
    })

    it("renders the empty state", () => {
        render(
            <SettingsRelationDetailList
                title="Linked Lenses"
                fallbackLabel="Lens"
                emptyMessage="No lenses associated with this camera."
                isDark={true}
                items={[]}
            />,
        )

        expect(screen.getByText("No lenses associated with this camera.")).toBeInTheDocument()
    })
})
