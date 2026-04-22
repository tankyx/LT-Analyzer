#!/usr/bin/env python3
"""
DEPRECATED. Do not run.

This script previously created an admin user in `race_data.db` with a hardcoded
SHA256 password. Both problems have been fixed:

  - The canonical auth database is `auth.db` (see initialize_databases.py).
  - Passwords are hashed with bcrypt, bootstrapped from the ADMIN_PASSWORD env var.

Use `python initialize_databases.py` instead.
"""

import sys

sys.stderr.write(
    'setup_auth_db.py is deprecated. Run `python initialize_databases.py` '
    'after setting ADMIN_USERNAME/ADMIN_PASSWORD in .env.\n'
)
sys.exit(1)
