#!/bin/bash
# AWS SSM Parameter Store에서 /trakit 파라미터를 조회하여 .env 파일 생성
#
# 사전 조건:
#   - AWS CLI 설치 및 설정
#   - EC2 IAM Role에 ssm:GetParametersByPath, kms:Decrypt 권한
#
# 사용법: cd backend && bash fetch-env.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
SSM_PATH="/trakit"

echo "📥 AWS Parameter Store에서 .env 생성 중..."

if ! command -v aws &> /dev/null; then
  echo "❌ AWS CLI가 설치되어 있지 않습니다."
  exit 1
fi

PARAMS=$(aws ssm get-parameters-by-path \
  --path "$SSM_PATH" \
  --with-decryption \
  --query "Parameters[*].[Name,Value]" \
  --output text 2>&1)

if [ $? -ne 0 ]; then
  echo "❌ Parameter Store 조회 실패:"
  echo "$PARAMS"
  exit 1
fi

if [ -z "$PARAMS" ]; then
  echo "❌ $SSM_PATH 경로에 파라미터가 없습니다."
  exit 1
fi

echo "$PARAMS" | while read name value; do
  key=$(echo "$name" | sed "s|${SSM_PATH}/||")
  echo "$key=$value"
done > "$ENV_FILE"

echo "✅ $ENV_FILE 생성 완료:"
cat "$ENV_FILE" | sed 's/=.*/=****/'
