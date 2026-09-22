# V2 Collector Extension

Manifest V3 的 Profile、Replies、Search 采集与受控父帖补全适配器。源码在 `src/`，构建产物在 `dist/`；只向本地 Backend 提交公开内容和临时健康信息。

在本目录执行 `npm test`、`npm run typecheck`、`npm run build`。浏览器手动加载步骤见[运行指南](../../docs/v2/local-development.md)，父帖边界见[架构](../../docs/v2/architecture.md)。

磁盘构建成功不证明 Edge 已加载该目录或版本，实际加载需在扩展详情核实。不要删除正在加载的 dist。
