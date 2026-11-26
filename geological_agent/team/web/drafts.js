'use strict';
(() => {
  let uid = null, database = null;
  const pending = new Map();
  const available = typeof indexedDB === 'object' && indexedDB !== null;

  function prefix(scope) { return 'orebogao:draft:v1:' + encodeURIComponent(uid || 'anonymous') + ':' + encodeURIComponent(scope); }
  function key(scope, field) { return prefix(scope) + ':' + field; }
  function write(scope, field, value) {
    try { localStorage.setItem(key(scope, field), value); } catch (_) { /* Storage can be disabled without losing the in-memory draft. */ }
  }
  function remove(scope, field) {
    try { localStorage.removeItem(key(scope, field)); } catch (_) { /* Nothing to remove when storage is unavailable. */ }
  }
  function open() {
    if (!available) return Promise.reject(new Error('浏览器不支持本机附件草稿'));
    if (database) return Promise.resolve(database);
    return new Promise((resolve, reject) => {
      const request = indexedDB.open('orebogao-research-drafts', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('files', {keyPath:'key'});
      request.onsuccess = () => { database = request.result; database.onversionchange = () => database.close(); resolve(database); };
      request.onerror = () => { database = null; reject(request.error || new Error('无法打开本机附件草稿')); };
    });
  }
  async function transaction(mode, action) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('files', mode), store = tx.objectStore('files');
      let result;
      try { result = action(store); } catch (error) { tx.abort(); reject(error); return; }
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(tx.error || new Error('本机附件草稿操作失败'));
      tx.onabort = () => reject(tx.error || new Error('本机附件草稿操作已取消'));
    });
  }
  function save(scope, field, value) {
    if (!uid) return;
    const target = key(scope, field);
    clearTimeout(pending.get(target)?.timer);
    const timer = setTimeout(() => { write(scope, field, value); pending.delete(target); }, 120);
    pending.set(target, {scope, field, value, timer});
  }
  function text(scope, field = 'text') {
    if (!uid) return '';
    try { return localStorage.getItem(key(scope, field)) || ''; } catch (_) { return ''; }
  }
  function clear(scope) {
    for (const field of ['text', 'option', 'plan']) remove(scope, field);
    for (const target of pending.keys()) if (target.startsWith(prefix(scope) + ':')) { clearTimeout(pending.get(target).timer); pending.delete(target); }
    if (!uid || !available) return Promise.resolve();
    return transaction('readwrite', store => {
      const request = store.getAllKeys();
      request.onsuccess = () => {
        for (const target of request.result) if (String(target).startsWith(prefix(scope) + ':file:')) store.delete(target);
      };
    }).catch(() => {});
  }
  async function putFile(scope, file) {
    if (!uid) throw new Error('请先登录再保存附件草稿');
    const target = key(scope, 'file:' + file.name);
    await transaction('readwrite', store => store.put({key:target, name:file.name, type:file.type, lastModified:file.lastModified, file}));
  }
  async function removeFile(scope, name) {
    if (!uid || !available) return;
    await transaction('readwrite', store => store.delete(key(scope, 'file:' + name)));
  }
  async function files(scope) {
    if (!uid || !available) return [];
    let rows = [];
    await transaction('readonly', store => {
      const request = store.getAll();
      request.onsuccess = () => { rows = request.result; };
    });
    return rows.filter(row => String(row.key).startsWith(prefix(scope) + ':file:'))
      .map(row => new File([row.file], row.name, {type:row.type, lastModified:row.lastModified}));
  }
  function flush() {
    for (const {scope, field, value, timer} of pending.values()) { clearTimeout(timer); write(scope, field, value); }
    pending.clear();
  }
  window.OreSageDrafts = {
    identity(next) { flush(); uid = next || null; },
    reset() { flush(); uid = null; },
    save, text, clear, putFile, removeFile, files, flush
  };
  window.addEventListener('pagehide', flush);
})();
