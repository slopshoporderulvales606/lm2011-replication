#!/usr/bin/env bash
# Runs the full variant grid: alternative panels (data-side) + regression
# comparison grid (step 8).
#
# Order — step 4 (slow, 15 min) is run twice: once per dictionary rule.
#         Each step-4 rule's sparse matrices feed the downstream step 5 + 6
#         before step 4 is re-run with the next rule.

set -e
PY=/c/Users/Hank_desktop/anaconda3/envs/py310/python.exe
ROOT=/d/lm2011-replication
cd "$ROOT"

echo "############################################################"
echo "# Variant 1: dictionary rule = 'positive' (excludes -2020 words)"
echo "############################################################"
LM_DICT_RULE="positive" $PY code/step4_word_counts.py 2>&1 | tail -8
LM_SHRCD="10,11,12" LM_LINK_MODE="compustat_only" LM_RUN_TAG="dict_pos_only" \
    $PY code/step5_build_sample.py 2>&1 | tail -16
FF48_SIC_SOURCE="crsp" $PY code/step6_build_panel.py 2>&1 | tail -5
cp -f output/panel.parquet output/panel_dict_pos_only.parquet
echo "  saved: output/panel_dict_pos_only.parquet"

echo ""
echo "############################################################"
echo "# Restore default dictionary (rule = 'nonzero') + re-run step 4"
echo "############################################################"
LM_DICT_RULE="nonzero" $PY code/step4_word_counts.py 2>&1 | tail -8
LM_SHRCD="10,11,12" LM_LINK_MODE="compustat_only" LM_RUN_TAG="default_baseline" \
    $PY code/step5_build_sample.py 2>&1 | tail -16
FF48_SIC_SOURCE="crsp" $PY code/step6_build_panel.py 2>&1 | tail -5
cp -f output/panel.parquet output/panel_default.parquet
echo "  saved: output/panel_default.parquet"

echo ""
echo "############################################################"
echo "# Variant 2: link mode = 'compustat_with_comphist'"
echo "############################################################"
LM_SHRCD="10,11,12" LM_LINK_MODE="compustat_with_comphist" LM_RUN_TAG="link_with_comphist" \
    $PY code/step5_build_sample.py 2>&1 | tail -16
FF48_SIC_SOURCE="crsp" $PY code/step6_build_panel.py 2>&1 | tail -5
cp -f output/panel.parquet output/panel_link_with_comphist.parquet
echo "  saved: output/panel_link_with_comphist.parquet"

echo ""
echo "############################################################"
echo "# Variant 3 + 4: alternative shrcd combos (data-side)"
echo "############################################################"
LM_SHRCD="10,11" LM_LINK_MODE="compustat_only" LM_RUN_TAG="shrcd_10_11" \
    $PY code/step5_build_sample.py 2>&1 | tail -16
FF48_SIC_SOURCE="crsp" $PY code/step6_build_panel.py 2>&1 | tail -5
cp -f output/panel.parquet output/panel_shrcd_10_11.parquet

LM_SHRCD="10,11,12,18" LM_LINK_MODE="compustat_only" LM_RUN_TAG="shrcd_10_11_12_18" \
    $PY code/step5_build_sample.py 2>&1 | tail -16
FF48_SIC_SOURCE="crsp" $PY code/step6_build_panel.py 2>&1 | tail -5
cp -f output/panel.parquet output/panel_shrcd_10_11_12_18.parquet

echo ""
echo "############################################################"
echo "# Variant 5 + 6: alternative SIC sources for FF48"
echo "############################################################"
LM_SHRCD="10,11,12" LM_LINK_MODE="compustat_only" LM_RUN_TAG="final" \
    $PY code/step5_build_sample.py 2>&1 | tail -16
FF48_SIC_SOURCE="sich" $PY code/step6_build_panel.py 2>&1 | tail -5
cp -f output/panel.parquet output/panel_sic_sich.parquet
FF48_SIC_SOURCE="sic" $PY code/step6_build_panel.py 2>&1 | tail -5
cp -f output/panel.parquet output/panel_sic_sic.parquet

# Restore default panel
FF48_SIC_SOURCE="crsp" $PY code/step6_build_panel.py 2>&1 | tail -5
cp -f output/panel.parquet output/panel_default.parquet

echo ""
echo "############################################################"
echo "# Step 8: regression-side variant grid on all panels"
echo "############################################################"
$PY code/step8_variant_grid.py 2>&1 | tail -50

echo ""
echo "############################################################"
echo "# DONE"
echo "############################################################"
ls -la output/panel_*.parquet output/variant_grid_results.csv
