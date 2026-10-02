#!/usr/bin/env bash
# Rebuild everything from raw data to dashboard mockups. Run from the repository root.
#   MYSQL      mysql client command (default: "mysql -uroot")
#   MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD   for the Python scripts (see python/db.py)
#   REGENERATE=1  also regenerate the synthetic raw data first
set -euo pipefail
PY=${PY:-$( [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3 )}

if [ "${REGENERATE:-0}" = "1" ]; then
  echo "== 0. generate synthetic data";        $PY python/generate_data.py
fi
echo "== 1. MySQL: schema, load, data quality, star schema, views";  sql/run_all.sh > /dev/null
echo "== 2. validate pipeline (41 checks)";   $PY python/validate_pipeline.py | tail -1
echo "== 3. advanced analytics";              (cd python && ../$PY advanced_analytics.py | grep "Root cause")
echo "== 4. scores and DAX expected values";  (cd python && ../$PY scoring_and_expected_values.py > /dev/null)
echo "== 5. dashboard mockups";               (cd python && ../$PY render_dashboard_mockups.py)
echo "== 6. copy page images to screenshots/ (labelled _mockup)"
for f in powerbi/mockups/*.png; do cp "$f" "screenshots/$(basename "$f" .png)_mockup.png"; done
