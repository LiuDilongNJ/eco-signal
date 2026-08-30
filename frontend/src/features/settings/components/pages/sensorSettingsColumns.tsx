import type { ColumnDef } from "../../../project/components/data/DataPageLayout"

export const SENSOR_COLUMNS: ColumnDef[] = [
    { key: "sensor_id", label: "ID", type: "number", width: "96px", sortable: true, filterable: true, ellipsis: false },
    { key: "uuid", label: "UUID", type: "text", width: "320px", sortable: true, filterable: true, ellipsis: false },
    {
        key: "name",
        label: "Name",
        type: "text",
        width: "240px",
        sortable: true,
        filterable: true,
        ellipsis: false,
        renderCell: (value) => (
            <span className="sensor-settings__name-cell">
                <span className="sensor-settings__name">{String(value ?? "")}</span>
            </span>
        ),
    },
    {
        key: "sensor_type",
        label: "Type",
        type: "text",
        width: "120px",
        sortable: true,
        filterable: true,
        ellipsis: false,
    },
    { key: "recorder_name", label: "Recorder", type: "text", width: "280px", sortable: true, filterable: true, ellipsis: false },
    { key: "microphone_name", label: "Microphone", type: "text", width: "280px", sortable: true, filterable: true, ellipsis: false },
    { key: "camera_name", label: "Camera", type: "text", width: "280px", sortable: true, filterable: true, ellipsis: false },
    { key: "lens_name", label: "Lens", type: "text", width: "280px", sortable: true, filterable: true, ellipsis: false },
    { key: "description", label: "Description", type: "text", width: "360px", filterable: true, ellipsis: false },
    {
        key: "creation_date",
        label: "Created",
        type: "date",
        width: "180px",
        sortable: true,
        filterable: true,
        filterType: "dateRange",
        filterShowTime: false,
        ellipsis: false,
    },
]
