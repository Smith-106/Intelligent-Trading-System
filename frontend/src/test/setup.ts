/**
 * Vitest 全局 setup（所有测试文件共享，见 vitest.config.ts 的 setupFiles）。
 *
 * 两件事：
 * 1. 引入 jest-dom 的 Vitest 适配层 —— 注册 toBeInTheDocument / toHaveTextContent
 *    等断言，并附带类型增强（显式 import，不依赖 vitest/globals）。
 * 2. RTL 自动清理：项目未开启 vitest globals，@testing-library/react 无法
 *    自动挂载全局 afterEach，这里手动接一次，防止用例间 DOM 泄漏。
 */

import "@testing-library/jest-dom/vitest";

import { afterEach } from "vitest";

import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});
