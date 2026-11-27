/**
 * Typed draft persistence module matching `window.OreSageDrafts`.
 * Handles debounced localStorage text drafts and IndexedDB file drafts
 * with safe graceful degradation when browser storage is unavailable.
 */

export interface DraftsApi {
  identity: (next: string | null | undefined) => void;
  reset: () => void;
  save: (scope: string, field: string, value: string) => void;
  text: (scope: string, field?: string) => string;
  clear: (scope: string) => Promise<void>;
  putFile: (scope: string, file: File) => Promise<void>;
  removeFile: (scope: string, name: string) => Promise<void>;
  files: (scope: string) => Promise<File[]>;
  flush: () => void;
}

interface PendingWrite {
  scope: string;
  field: string;
  value: string;
  timer: ReturnType<typeof setTimeout>;
}

interface StoredFileRow {
  key: string;
  name: string;
  type: string;
  lastModified: number;
  file: Blob;
}

export interface DraftsOptions {
  debounceMs?: number;
  storage?: Storage | null;
  idbFactory?: IDBFactory | null;
  bindPageHide?: boolean;
}

export function createDraftsStore(options: DraftsOptions = {}): DraftsApi {
  const debounceMs = options.debounceMs ?? 120;
  const storage: Storage | null =
    options.storage !== undefined
      ? options.storage
      : typeof localStorage !== 'undefined'
        ? localStorage
        : null;
  const idb: IDBFactory | null =
    options.idbFactory !== undefined
      ? options.idbFactory
      : typeof indexedDB === 'object' && indexedDB !== null
        ? indexedDB
        : null;

  let uid: string | null = null;
  let database: IDBDatabase | null = null;
  const pending = new Map<string, PendingWrite>();

  const prefix = (scope: string): string =>
    `orebogao:draft:v1:${encodeURIComponent(uid || 'anonymous')}:${encodeURIComponent(scope)}`;

  const storageKey = (scope: string, field: string): string => `${prefix(scope)}:${field}`;

  function write(scope: string, field: string, value: string): void {
    if (!storage) return;
    try {
      storage.setItem(storageKey(scope, field), value);
    } catch {
      /* Storage can be disabled without losing the in-memory draft. */
    }
  }

  function remove(scope: string, field: string): void {
    if (!storage) return;
    try {
      storage.removeItem(storageKey(scope, field));
    } catch {
      /* Nothing to remove when storage is unavailable. */
    }
  }

  function openDb(): Promise<IDBDatabase> {
    if (!idb) return Promise.reject(new Error('浏览器不支持本机附件草稿'));
    if (database) return Promise.resolve(database);
    return new Promise((resolve, reject) => {
      const request = idb.open('orebogao-research-drafts', 1);
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains('files')) {
          request.result.createObjectStore('files', { keyPath: 'key' });
        }
      };
      request.onsuccess = () => {
        database = request.result;
        database.onversionchange = () => {
          database?.close();
          database = null;
        };
        resolve(database);
      };
      request.onerror = () => {
        database = null;
        reject(request.error ?? new Error('无法打开本机附件草稿'));
      };
    });
  }

  async function runTx<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => T): Promise<T> {
    const db = await openDb();
    return new Promise<T>((resolve, reject) => {
      const tx = db.transaction('files', mode);
      const store = tx.objectStore('files');
      let result: T;
      try {
        result = action(store);
      } catch (err) {
        tx.abort();
        reject(err);
        return;
      }
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(tx.error ?? new Error('本机附件草稿操作失败'));
      tx.onabort = () => reject(tx.error ?? new Error('本机附件草稿操作已取消'));
    });
  }

  function flush(): void {
    for (const entry of pending.values()) {
      clearTimeout(entry.timer);
      write(entry.scope, entry.field, entry.value);
    }
    pending.clear();
  }

  function save(scope: string, field: string, value: string): void {
    if (!uid) return;
    const target = storageKey(scope, field);
    const prev = pending.get(target);
    if (prev) clearTimeout(prev.timer);
    const timer = setTimeout(() => {
      write(scope, field, value);
      pending.delete(target);
    }, debounceMs);
    pending.set(target, { scope, field, value, timer });
  }

  function text(scope: string, field = 'text'): string {
    if (!uid || !storage) return '';
    try {
      return storage.getItem(storageKey(scope, field)) || '';
    } catch {
      return '';
    }
  }

  function clear(scope: string): Promise<void> {
    for (const field of ['text', 'option', 'plan']) {
      remove(scope, field);
    }
    const scopePrefix = `${prefix(scope)}:`;
    for (const [target, entry] of pending.entries()) {
      if (target.startsWith(scopePrefix)) {
        clearTimeout(entry.timer);
        pending.delete(target);
      }
    }
    if (!uid || !idb) return Promise.resolve();
    return runTx('readwrite', (store) => {
      const req = store.getAllKeys();
      req.onsuccess = () => {
        const filePrefix = `${prefix(scope)}:file:`;
        for (const key of req.result) {
          if (String(key).startsWith(filePrefix)) {
            store.delete(key);
          }
        }
      };
    })
      .then(() => undefined)
      .catch(() => undefined);
  }

  async function putFile(scope: string, file: File): Promise<void> {
    if (!uid) throw new Error('请先登录再保存附件草稿');
    const target = storageKey(scope, `file:${file.name}`);
    await runTx('readwrite', (store) => {
      store.put({
        key: target,
        name: file.name,
        type: file.type,
        lastModified: file.lastModified,
        file,
      } satisfies StoredFileRow);
    });
  }

  async function removeFile(scope: string, name: string): Promise<void> {
    if (!uid || !idb) return;
    await runTx('readwrite', (store) => {
      store.delete(storageKey(scope, `file:${name}`));
    });
  }

  async function files(scope: string): Promise<File[]> {
    if (!uid || !idb) return [];
    let rows: StoredFileRow[] = [];
    await runTx('readonly', (store) => {
      const req = store.getAll();
      req.onsuccess = () => {
        rows = (req.result as StoredFileRow[]) ?? [];
      };
    });
    const filePrefix = `${prefix(scope)}:file:`;
    return rows
      .filter((row) => String(row.key).startsWith(filePrefix))
      .map((row) => new File([row.file], row.name, { type: row.type, lastModified: row.lastModified }));
  }

  if (options.bindPageHide !== false && typeof window !== 'undefined') {
    window.addEventListener('pagehide', flush);
  }

  return {
    identity(next) {
      flush();
      uid = next || null;
    },
    reset() {
      flush();
      uid = null;
    },
    save,
    text,
    clear,
    putFile,
    removeFile,
    files,
    flush,
  };
}
