#!/usr/bin/env bash
# Cron-friendly wrapper to settle auctions
set -euo pipefail
python manage.py settle_auctions --limit=${SETTLEMENT_LIMIT:-200}
