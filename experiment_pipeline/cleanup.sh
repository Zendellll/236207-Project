#!/bin/bash
# Cleanup runtime files inside experiment_pipeline/
# Does NOT touch any data in mock_internet/ or poc/

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Cleaning up experiment_pipeline runtime files..."

rm -rf "$SCRIPT_DIR/vector_db_active"
echo "  Removed vector database"

rm -rf "$SCRIPT_DIR/logs"
echo "  Removed logs"

rm -f "$SCRIPT_DIR/experiment_results.csv"
echo "  Removed default results file"

find "$SCRIPT_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
echo "  Removed Python cache"

echo ""
echo "Done! To re-run experiments:"
echo "  cd experiment_pipeline/"
echo "  python run_pipeline.py --list"
echo "  python run_pipeline.py --phases clean"
