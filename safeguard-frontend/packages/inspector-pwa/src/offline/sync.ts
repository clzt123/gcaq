import { offlineQueue } from './queue';
import { hazardApi } from '@safeguard/shared';

export function setupOfflineSync() {
  window.addEventListener('online', async () => {
    console.log('[PWA] 网络已恢复，开始同步离线数据...');
    try {
      const result = await offlineQueue.flush(async (task) => {
        if (task.type === 'hazard_report') {
          await hazardApi.analyze(task.payload);
        }
        return true;
      });
      if (result.success > 0 || result.failed > 0) {
        console.log(`[PWA] 同步完成: ${result.success} 成功, ${result.failed} 失败`);
      }
    } catch (err) {
      console.error('[PWA] 同步失败:', err);
    }
  });
}
