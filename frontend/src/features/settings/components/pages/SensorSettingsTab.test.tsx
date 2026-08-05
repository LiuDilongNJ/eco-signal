import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it } from "vitest"

import { SENSOR_COLUMNS } from "./sensorSettingsColumns"

function renderNameCell(isDefault: boolean): ReactNode {
    const nameColumn = SENSOR_COLUMNS.find((column) => column.key === "name")
    return nameColumn?.renderCell?.("Sensor 100", { is_default: isDefault })
}

describe("SensorSettingsTab columns", () => {
    it("shows the default label only for default sensors", () => {
        const { rerender } = render(<>{renderNameCell(true)}</>)

        expect(screen.getByText("Sensor 100")).toBeInTheDocument()
        expect(screen.getByText("default")).toBeInTheDocument()

        rerender(<>{renderNameCell(false)}</>)

        expect(screen.getByText("Sensor 100")).toBeInTheDocument()
        expect(screen.queryByText("default")).not.toBeInTheDocument()
    })
})
