import { render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it } from "vitest"

import { SENSOR_COLUMNS } from "./sensorSettingsColumns"

function renderNameCell(): ReactNode {
    const nameColumn = SENSOR_COLUMNS.find((column) => column.key === "name")
    return nameColumn?.renderCell?.("Sensor 100", {})
}

describe("SensorSettingsTab columns", () => {
    it("renders the sensor name without a default label", () => {
        render(<>{renderNameCell()}</>)

        expect(screen.getByText("Sensor 100")).toBeInTheDocument()
        expect(screen.queryByText("default")).not.toBeInTheDocument()
    })
})
