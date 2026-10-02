#!/usr/bin/env bash
# Rebuild the database from scratch. Run from the repository root.
# MYSQL defaults to plain `mysql`; override for a custom client, e.g.
#   MYSQL="mysql --defaults-file=~/tools/mysql8-run/my.cnf -uroot" sql/run_all.sh
set -euo pipefail
MYSQL=${MYSQL:-"mysql -uroot"}
for f in sql/0[1-9]_*.sql; do
  echo "== $f"
  $MYSQL --local-infile=1 < "$f"
done
