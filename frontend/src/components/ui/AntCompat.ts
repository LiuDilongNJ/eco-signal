/**
 * Controlled compatibility surface for Ant Design APIs that have not yet
 * gained a semantic Eco-Signal adapter. Business code imports these through
 * @/components/ui so implementation ownership remains centralized.
 */
export {
    Alert,
    Col,
    Collapse,
    ConfigProvider,
    Descriptions,
    Divider,
    message,
    Popconfirm,
    Progress,
    Row,
    Space,
    Tag,
    theme,
    Typography,
} from "antd"

export type {
    ThemeConfig,
} from "antd"
