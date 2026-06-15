interface OfflineTask {
  id: string;
  type: 'hazard_report' | 'ticket_update';
  payload: any;
  timestamp: number;
  retryCount: number;
}

const DB_NAME = 'safeguard-offline';
const STORE_NAME = 'offline-tasks';
const MAX_RETRY = 3;

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore(STORE_NAME, { keyPath: 'id' });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export class OfflineQueue {
  async enqueue(task: OfflineTask): Promise<void> {
    const db = await openDB();
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).add(task);
    return new Promise((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  async pendingCount(): Promise<number> {
    const db = await openDB();
    const tx = db.transaction(STORE_NAME, 'readonly');
    const req = tx.objectStore(STORE_NAME).count();
    return new Promise((resolve, reject) => {
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async getAll(): Promise<OfflineTask[]> {
    const db = await openDB();
    const tx = db.transaction(STORE_NAME, 'readonly');
    const req = tx.objectStore(STORE_NAME).getAll();
    return new Promise((resolve, reject) => {
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async remove(id: string): Promise<void> {
    const db = await openDB();
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).delete(id);
    return new Promise((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  async flush(executor: (task: OfflineTask) => Promise<boolean>): Promise<{ success: number; failed: number }> {
    const tasks = await this.getAll();
    let success = 0;
    let failed = 0;

    for (const task of tasks) {
      if (task.retryCount >= MAX_RETRY) {
        await this.remove(task.id);
        failed++;
        continue;
      }
      try {
        const ok = await executor(task);
        if (ok) { await this.remove(task.id); success++; }
        else { task.retryCount++; failed++; }
      } catch { task.retryCount++; failed++; }
    }

    return { success, failed };
  }
}

export const offlineQueue = new OfflineQueue();
