"""Driver-alias endpoints (public read, admin CRUD)."""
import sqlite3

from flask import Blueprint, jsonify, request

import race_ui

from race_ui import (
    admin_required,
)


aliases_bp = Blueprint('aliases', __name__)


@aliases_bp.route('/api/driver/aliases', methods=['GET'])
def get_driver_aliases():
    """Return the alias group for a driver name (canonical + all aliases).

    Query param: name (required). Case-insensitive.
    """
    raw = request.args.get('name', '').strip()
    if not raw:
        return jsonify({'error': 'name parameter is required'}), 400
    try:
        with race_ui.get_db_connection() as conn:
            # Find canonicals reachable from the input name
            rows = conn.execute(
                '''SELECT id, canonical_name, alias_name, added_by, added_at FROM driver_aliases
                   WHERE canonical_name = ? COLLATE NOCASE
                      OR alias_name     = ? COLLATE NOCASE''',
                (raw, raw),
            ).fetchall()
            canonicals = {r['canonical_name'] for r in rows}
            if not canonicals:
                canonicals.add(raw)
            # Pull every row in those canonicals' groups for display
            all_rows = []
            seen_ids = set()
            for c in canonicals:
                for r in conn.execute(
                    '''SELECT id, canonical_name, alias_name, added_by, added_at FROM driver_aliases
                       WHERE canonical_name = ? COLLATE NOCASE''',
                    (c,),
                ).fetchall():
                    if r['id'] in seen_ids:
                        continue
                    seen_ids.add(r['id'])
                    all_rows.append(dict(r))
        return jsonify({
            'canonical_names': sorted(canonicals, key=str.lower),
            'aliases': all_rows,
        })
    except Exception as e:
        race_ui.app.logger.exception('get_driver_aliases failed')
        return race_ui._internal_error(e)


@aliases_bp.route('/api/admin/aliases', methods=['GET'])
@admin_required
def admin_list_aliases():
    """List every alias row, grouped by canonical name."""
    try:
        with race_ui.get_db_connection() as conn:
            rows = conn.execute(
                '''SELECT id, canonical_name, alias_name, added_by, added_at
                   FROM driver_aliases ORDER BY canonical_name COLLATE NOCASE, alias_name COLLATE NOCASE'''
            ).fetchall()
        groups = {}
        for r in rows:
            groups.setdefault(r['canonical_name'], []).append({
                'id': r['id'],
                'alias_name': r['alias_name'],
                'added_by': r['added_by'],
                'added_at': r['added_at'],
            })
        return jsonify({
            'groups': [
                {'canonical_name': k, 'aliases': v}
                for k, v in sorted(groups.items(), key=lambda kv: kv[0].lower())
            ],
        })
    except Exception as e:
        race_ui.app.logger.exception('admin_list_aliases failed')
        return race_ui._internal_error(e)


@aliases_bp.route('/api/admin/aliases', methods=['POST'])
@admin_required
def admin_add_alias():
    """Add an alias mapping.

    Body JSON: { canonical_name, alias_name }
    """
    data = request.json or {}
    canonical = (data.get('canonical_name') or '').strip()
    alias = (data.get('alias_name') or '').strip()
    if not canonical or not alias:
        return jsonify({'error': 'canonical_name and alias_name are required'}), 400
    if canonical.lower() == alias.lower():
        return jsonify({'error': 'canonical and alias cannot be identical'}), 400
    try:
        added_by = getattr(request, 'current_user', {}).get('username') or 'admin'
        with race_ui.get_db_connection() as conn:
            cur = conn.execute(
                '''INSERT INTO driver_aliases (canonical_name, alias_name, added_by)
                   VALUES (?, ?, ?)''',
                (canonical, alias, added_by),
            )
            new_id = cur.lastrowid
        race_ui._audit('admin_alias_added', actor_user_id=request.current_user['id'],
               target=f'{canonical}<-{alias}', details={'id': new_id})
        return jsonify({'success': True, 'id': new_id})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'This alias already exists for that canonical name'}), 409
    except Exception as e:
        race_ui.app.logger.exception('admin_add_alias failed')
        return race_ui._internal_error(e)


@aliases_bp.route('/api/admin/aliases/<int:alias_id>', methods=['DELETE'])
@admin_required
def admin_delete_alias(alias_id):
    """Remove a single alias mapping by id."""
    try:
        with race_ui.get_db_connection() as conn:
            cur = conn.execute('DELETE FROM driver_aliases WHERE id = ?', (alias_id,))
            if cur.rowcount == 0:
                return jsonify({'error': 'alias not found'}), 404
        race_ui._audit('admin_alias_removed', actor_user_id=request.current_user['id'],
               target=str(alias_id))
        return jsonify({'success': True})
    except Exception as e:
        race_ui.app.logger.exception('admin_delete_alias failed')
        return race_ui._internal_error(e)
