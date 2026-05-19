#!/usr/bin/env bash

set -e

# -----------------------------
# Conda 환경 활성화
# -----------------------------
source /c/Users/seohyun/anaconda3/etc/profile.d/conda.sh
conda activate rag

PYTHON="/c/Users/seohyun/anaconda3/envs/rag/python.exe"
$PYTHON --version
$PYTHON -c "import sys; print(sys.executable)"

# -----------------------------
# 실험 설정
# -----------------------------
LLMS=("openai" "gemini")
DBS=("./chroma_db/v4" "./chroma_db/v5" "./chroma_db/v6")

TOTAL=$(( ${#LLMS[@]} * ${#DBS[@]} ))
COUNT=0

echo "=================================================="
echo "  Week4 Chunking Experiment  (총 ${TOTAL}회)"
echo "=================================================="

for llm in "${LLMS[@]}"; do
    for db in "${DBS[@]}"; do

        COUNT=$(( COUNT + 1 ))
        db_ver=$(basename "$db")

        echo ""
        echo "--------------------------------------------------"
        echo "  [${COUNT}/${TOTAL}] judge=${llm} | db=${db_ver}"
        echo "--------------------------------------------------"

        $PYTHON src/evaluate.py \
            --llm "$llm" \
            --db "$db"

        echo "완료: results/ragas_${llm}_${db_ver}_*.json"

    done
done

echo ""
echo "=================================================="
echo "  전체 실험 완료"
echo "=================================================="

ls -1 results/ragas_*.json 2>/dev/null || echo "결과 파일 없음"