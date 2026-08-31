# EcoSignal Frontend

基于 **React 18 + Vite + TypeScript** 的生态声学数据管理平台前端。

---

## 技术栈

| 分类       | 技术                    | 说明                   |
| ---------- | ----------------------- | ---------------------- |
| 核心       | React 18 + TypeScript   | 组件库 + 严格类型      |
| 构建       | Vite 6 (SWC)            | 快速构建与热更新       |
| 路由       | React Router v6         | 页面导航，支持懒加载   |
| 状态管理   | Zustand v5              | 轻量级全局状态         |
| 样式       | Tailwind CSS v4         | 原子化 CSS + 自定义 CSS |
| UI 组件    | Ant Design + Lucide Icons | 可定制组件 + 图标库     |
| 地图       | Leaflet + react-leaflet v4 | 交互式地图展示      |
| 数据请求   | TanStack Query v5       | API 缓存与同步（预留） |
| 表格       | TanStack Table v8       | 无头表格组件（预留）   |
| 表单       | React Hook Form + Zod   | 表单验证（预留）       |

---

## 快速开始

```bash
# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 生产构建
npm run build

# 预览构建产物
npm run preview
```

如果你是通过仓库根目录的 Docker Compose 运行整套应用，前端访问入口由根目录 `.env` 中的 `FRONTEND_PORT` 控制，默认是 `http://localhost`。

## 项目结构

```
src/
├── api/                               # API 请求客户端与接口定义
├── components/                        # 全局通用组件
│   ├── layout/                        # 页面基础布局框架
│   └── ui/                            # 基础通用 UI 组件
├── features/                          # 核心业务功能模块 (按功能内聚划分)
│   ├── errors/                        # 错误异常处理页面 (如 404 等)
│   ├── example/                       # 示例参考模块
│   ├── home/                          # 首页核心业务与布局
│   ├── project/                       # 项目与数据管理核心模块
│   │   ├── components/                # 项目内部私有业务组件
│   │   │   ├── data/                  # 数据管理与各种列表清单子页面
│   │   │   ├── modals/                # 对话框、面板、抽屉等统一管理
│   │   │   ├── nav/                   # 项目内导航栏、过滤切换组合
│   │   │   └── tabs/                  # 详情页的各标签切分(地图, 数据等)
│   │   ├── data/                      # 包含分类学、系统常量设定选项及模拟数据
│   │   ├── pages/                     # 本特征的核心主页面挂载点
│   │   └── stores/                    # 项目范围专属的状态机库 (Zustand)
│   └── settings/                      # 基础设置与账户环境偏好首选项
├── hooks/                             # 跨模块通用 React Hooks 钩子
├── lib/                               # 库或工具方法的重新封装 (如 utils)
├── providers/                         # 全局上下文依赖注射器 (Auth, Theme 等)
├── router/                            # React Router DOM 页面层级基础路由设定 
├── store/                             # Root Global 层级的全局响应状态管中心
├── test/                              # 测试配置框架设置档
├── types/                             # 全局共享 Type Definition 类型及接口集合
├── utils/                             # 实用工具包集合函数 (如 auth 等)
├── App.tsx                            # React Web 渲染总应用模块入口
├── main.tsx                           # 工程运行渲染主文件挂载点
├── index.css                          # 全局样式配置
└── vite-env.d.ts                      # Vite 框架类型及环境声明定义
```

---

## 可用脚本

| 命令                   | 说明             |
| ---------------------- | ---------------- |
| `npm run dev`          | 启动开发服务器   |
| `npm run build`        | TypeScript + 构建 |
| `npm run preview`      | 预览生产构建     |
| `npm run lint`         | ESLint 代码检查  |

---


## 环境变量

复制 `.env.example` 为 `.env.local`：

| 变量               | 说明       | 默认值      |
| ------------------ | ---------- | ----------- |
| `VITE_API_BASE_URL` | API 根路径（优先）。开发时未设置则固定为 `/api`（走 Vite 代理、避免 CORS） | `/api`      |
| `VITE_API_URL`     | 生产 / `vite preview` 用；`npm run dev` 不读取，请走代理 | — |
| `VITE_APP_TITLE`   | 应用标题   | `EcoSignal` |
| `VITE_CARTO_BASEMAP_KEY` | CARTO 栅格底图 API Key | — |

若接口大量 **500**，多为后端异常（如数据库未启动）。本地可看后端终端日志；`ENVIRONMENT=local` 时响应体里 `detail` 常带具体错误信息。

---

## License

Private
