"""Administrator-only, read-only account directory. Never select auth secrets."""
from fastapi import Request, HTTPException


def install_admin_user_routes(app, auth, store):
    @app.get('/api/admin/users')
    def list_users(request: Request, q: str = '', status: str = 'active',
                   page: int = 1, page_size: int = 50):
        auth(request, admin=True)
        q = q.strip()
        if len(q) > 200 or status not in ('all', 'active', 'disabled'):
            raise HTTPException(400, 'Invalid search or account status')
        if not 1 <= page <= 100000 or not 1 <= page_size <= 100:
            raise HTTPException(400, 'Invalid page or page size')
        joins = (' FROM users u LEFT JOIN user_profiles p ON p.user_id=u.id'
                 ' LEFT JOIN email_identities e ON e.user_id=u.id'
                 ' LEFT JOIN registration_details d ON d.user_id=u.id')
        conditions, params = [], []
        if status != 'all':
            conditions.append('u.disabled=?')
            params.append(int(status == 'disabled'))
        if q:
            escaped = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            conditions.append('(' + ' OR '.join(
                field + " LIKE ? ESCAPE '\\'" for field in
                ('u.username', 'e.email', 'p.organization', 'd.research_area')) + ')')
            params.extend(['%' + escaped + '%'] * 4)
        where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        # One locked read snapshot keeps total, summary and rows consistent.
        with store.lock:
            db = store.db
            summary = dict(db.execute(
                'SELECT COUNT(*) total, COALESCE(SUM(u.disabled=0),0) active,'
                ' COUNT(e.user_id) verified_email, '
                ' COALESCE(SUM(d.user_id IS NULL),0) missing_registration_details' + joins).fetchone())
            total = db.execute('SELECT COUNT(*)' + joins + where, params).fetchone()[0]
            rows = db.execute(
                'SELECT u.id,u.username,u.role,u.disabled,e.email,e.verified_at AS email_verified_at,'
                ' p.organization,p.phone_number,p.phone_verified_at,p.registered_at,'
                ' d.research_area,d.gender,d.age' + joins + where +
                ' ORDER BY (p.registered_at IS NULL),p.registered_at DESC,u.username,u.id LIMIT ? OFFSET ?',
                [*params, page_size, (page - 1) * page_size]).fetchall()
        return {'items': [dict(row) for row in rows], 'total': total, 'page': page,
                'page_size': page_size, 'summary': summary}
