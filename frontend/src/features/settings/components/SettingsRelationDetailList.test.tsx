import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { SettingsRelationDetailList } from "./SettingsRelationDetailList"

describe("SettingsRelationDetailList", () => {
    it("renders names, fallback labels, notes, and default state", () => {
        render(
            <SettingsRelationDetailList
                title="Linked Recorders"
                fallbackLabel="Recorder"
                emptyMessage="No recorders associated."
                isDark={false}
                items={[
                    { id: 1, name: "Recorder A", isDefault: true, notes: "Primary recorder" },
                    { id: 2, name: null },
                ]}
            />,
        )

        expect(screen.getByText("Linked Recorders")).toBeInTheDocument()
        expect(screen.getByText("Recorder A")).toBeInTheDocument()
        expect(screen.getByText("Recorder #2")).toBeInTheDocument()
        expect(screen.getByText("Primary recorder")).toBeInTheDocument()
        expect(screen.getByText("default")).toBeInTheDocument()
    })

    it("renders the empty state", () => {
        render(
            <SettingsRelationDetailList
                title="Linked Cameras"
                fallbackLabel="Camera"
                emptyMessage="No cameras associated with this lens."
                isDark={true}
                items={[]}
            />,
        )

        expect(screen.getByText("No cameras associated with this lens.")).toBeInTheDocument()
    })
})
