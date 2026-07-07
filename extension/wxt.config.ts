import { defineConfig } from 'wxt';

const apiBase = (process.env.VITE_API_BASE || 'http://localhost:8080/api/v1').replace(/\/$/, '');
const apiOrigin = new URL(apiBase).origin;
const hostPermissions = Array.from(
  new Set([
    'http://localhost:8080/*',
    'http://127.0.0.1:8080/*',
    `${apiOrigin}/*`
  ])
);

export default defineConfig({
  modules: ['@wxt-dev/module-vue'],
  vite: () => ({
    build: {
      chunkSizeWarningLimit: 700
    }
  }),
  manifest: {
    name: '酒店竞对价格监控',
    description: '酒店竞对价格巡检、今日对比和运营判断',
    version: '0.1.1',
    permissions: ['storage', 'clipboardWrite'],
    host_permissions: hostPermissions,
    action: {
      default_title: '酒店竞对价格监控',
      default_popup: 'popup.html'
    }
  }
});
