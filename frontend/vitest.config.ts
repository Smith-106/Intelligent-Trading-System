/**
 * Vitest 单测配置（前端测试基建首建）。
 *
 * 与 vite.config.ts 的关系：仅复用其 resolve.alias（@ → ./src），
 * 不引入 tailwind/react 插件 —— 单测不需要样式编译与 HMR，
 * 保持测试启动开销最小。构建路径仍由 vite.config.ts 独占。
 */

import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      // 与 vite.config.ts 完全一致，保证测试内 @/xxx 导入解析行为相同
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    // jsdom 环境：覆盖 CopyableText 等需要 DOM 的组件与 Hook 测试
    environment: "jsdom",
    // 全局 setup：注册 jest-dom 匹配器与 RTL 自动清理（globals 关闭模式下需手动接 afterEach）
    setupFiles: ["./src/test/setup.ts"],
    // 覆盖率为可选能力：provider 固定 v8；实际执行 --coverage 前需先安装：
    //   npm i -D @vitest/coverage-v8
    coverage: {
      provider: "v8",
      include: ["src/**"],
      exclude: ["src/**/__tests__/**", "src/test/**"],
    },
  },
});
