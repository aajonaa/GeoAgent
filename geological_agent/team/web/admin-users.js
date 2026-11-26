'use strict';
(() => {
  const el = id => document.getElementById(id);
  let hooks, me, epoch = 0, page = 1, total = 0;
  const dialog = () => el('admin-users-dialog');
  const text = (tag, value, cls) => {
    const node = document.createElement(tag); node.textContent = value;
    if (cls) node.className = cls; return node;
  };
  function clear() {
    epoch++; me = null; el('admin-users-open').hidden = true;
    dialog().close(); el('admin-users-rows').replaceChildren();
    el('admin-users-summary').replaceChildren(); el('admin-users-search').value = '';
    el('admin-users-message').textContent = ''; el('admin-users-page').textContent = '';
  }
  async function load() {
    const ticket = ++epoch;
    el('admin-users-rows').replaceChildren(); el('admin-users-summary').replaceChildren();
    el('admin-users-message').textContent = '正在读取注册用户资料…';
    el('admin-users-prev').disabled = el('admin-users-next').disabled = true;
    try {
      const current = await hooks.api('/api/me');
      if (ticket !== epoch || !dialog().open) return;
      if (current.id !== me?.id || current.role !== 'admin') { clear(); location.reload(); return; }
      const query = new URLSearchParams({q: el('admin-users-search').value.trim(),
        status: el('admin-users-status').value, page: String(page), page_size: '50'});
      const data = await hooks.api('/api/admin/users?' + query);
      if (ticket !== epoch || !dialog().open) return;
      total = data.total;
      const s = data.summary;
      for (const [label, count] of [['账号总数',s.total],['启用账号',s.active],['已验证邮箱',s.verified_email],['缺少新增注册资料',s.missing_registration_details]]) {
        const card = text('div', '', 'admin-user-stat'); card.append(text('strong',String(count)),text('span',label)); el('admin-users-summary').append(card);
      }
      for (const user of data.items) {
        const row = document.createElement('tr');
        const registered = user.registered_at == null ? '历史账号：时间未知' : new Date(user.registered_at * 1000).toLocaleString('zh-CN');
        const gender = {male:'男',female:'女',other:'其他'}[user.gender] || '未填写';
        for (const value of [user.username, user.role === 'admin' ? '管理员' : '成员', user.disabled ? '已停用' : '启用', user.email || '未绑定',
          user.organization || '未填写',user.research_area || '未填写',gender,user.age == null ? '未填写' : String(user.age),user.phone_number || '未绑定',registered]) row.append(text('td',value));
        el('admin-users-rows').append(row);
      }
      el('admin-users-message').textContent = total ? `共找到 ${total} 个账号` : '没有符合条件的账号。';
      el('admin-users-page').textContent = `第 ${page} / ${Math.max(1,Math.ceil(total/50))} 页`;
      el('admin-users-prev').disabled = page <= 1;
      el('admin-users-next').disabled = page * 50 >= total;
    } catch (error) {
      if (ticket !== epoch) return;
      el('admin-users-rows').replaceChildren(); el('admin-users-summary').replaceChildren();
      el('admin-users-message').textContent = error.status === 403 ? '仅管理员可查看用户资料。' : '读取失败：' + error.message;
    }
  }
  function open() { if (me?.role !== 'admin') return; page = 1; dialog().showModal(); load(); }
  function session(user) {
    clear(); me = user; el('admin-users-open').hidden = user.role !== 'admin';
    if (location.pathname === '/admin/users' && user.role === 'admin') open();
  }
  function mount(value) {
    hooks = value;
    el('admin-users-open').addEventListener('click',open);
    el('admin-users-close').addEventListener('click',() => dialog().close());
    dialog().addEventListener('close',() => { epoch++; el('admin-users-rows').replaceChildren(); el('admin-users-summary').replaceChildren(); });
    el('admin-users-form').addEventListener('submit',event => { event.preventDefault(); page = 1; load(); });
    el('admin-users-status').addEventListener('change',() => { page = 1; load(); });
    el('admin-users-prev').addEventListener('click',() => { if (page > 1) {page--; load();} });
    el('admin-users-next').addEventListener('click',() => { if (page * 50 < total) {page++; load();} });
    document.addEventListener('visibilitychange',() => { if (dialog().open) { if (document.hidden) {epoch++; el('admin-users-rows').replaceChildren(); el('admin-users-summary').replaceChildren();} else load();} });
  }
  window.OreSageAdminUsers = {mount,session,clear};
})();
