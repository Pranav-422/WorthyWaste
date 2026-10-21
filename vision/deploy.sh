#!/usr/bin/env bash
# Build and deploy the vision Lambda, its S3 bucket, DynamoDB table and CloudWatch dashboard.
# Safe to re-run: each step creates the resource or updates it.
#
#   WW_VISION_KEY=<shared secret> ./deploy.sh
#
# Needs: aws CLI (configured), python 3.12. No Docker: Linux wheels are downloaded with pip --platform.
set -euo pipefail
cd "$(dirname "$0")"

REGION=${AWS_REGION:-ap-south-1}
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
NAME=ww-vision
BUCKET=worthywaste-vision-$ACCOUNT
TABLE=ww-vision-runs
ROLE=ww-vision-lambda
: "${WW_VISION_KEY:?set WW_VISION_KEY, the secret the backend sends in X-WW-Key}"
PY=${PYTHON:-.venv/Scripts/python}

echo "== S3 $BUCKET"
if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
    --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
fi
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
# Photos delete themselves after 30 days, like the DynamoDB items (TTL).
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" --lifecycle-configuration \
  '{"Rules":[{"ID":"expire-runs","Status":"Enabled","Filter":{"Prefix":"runs/"},"Expiration":{"Days":30}},
             {"ID":"expire-builds","Status":"Enabled","Filter":{"Prefix":"builds/"},"Expiration":{"Days":7}}]}'

echo "== DynamoDB $TABLE"
if ! aws dynamodb describe-table --table-name "$TABLE" --region "$REGION" >/dev/null 2>&1; then
  aws dynamodb create-table --table-name "$TABLE" --region "$REGION" --billing-mode PAY_PER_REQUEST \
    --attribute-definitions AttributeName=run_id,AttributeType=S --key-schema AttributeName=run_id,KeyType=HASH >/dev/null
  aws dynamodb wait table-exists --table-name "$TABLE" --region "$REGION"
fi
aws dynamodb update-time-to-live --table-name "$TABLE" --region "$REGION" \
  --time-to-live-specification Enabled=true,AttributeName=expires_at >/dev/null 2>&1 || true  # already on

echo "== IAM role $ROLE"
if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document \
    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name "$ROLE" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  sleep 10  # a new role takes a moment before Lambda accepts it
fi
aws iam put-role-policy --role-name "$ROLE" --policy-name ww-vision-data --policy-document "{
  \"Version\":\"2012-10-17\",\"Statement\":[
   {\"Effect\":\"Allow\",\"Action\":[\"s3:PutObject\",\"s3:GetObject\",\"s3:DeleteObject\"],\"Resource\":\"arn:aws:s3:::$BUCKET/runs/*\"},
   {\"Effect\":\"Allow\",\"Action\":[\"dynamodb:PutItem\",\"dynamodb:GetItem\",\"dynamodb:UpdateItem\",\"dynamodb:DeleteItem\"],
    \"Resource\":\"arn:aws:dynamodb:$REGION:$ACCOUNT:table/$TABLE\"}]}"
ROLE_ARN=$(aws iam get-role --role-name "$ROLE" --query Role.Arn --output text)

echo "== build"
rm -rf build/pkg build/$NAME.zip && mkdir -p build/pkg/models build/wheels
"$PY" -m pip download -q --only-binary=:all: --platform manylinux2014_x86_64 --python-version 3.12 \
  --implementation cp -d build/wheels -r requirements-lambda.txt
for w in build/wheels/*.whl; do "$PY" -c "import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$w" build/pkg; done
rm -rf build/pkg/numpy/*/tests build/pkg/numpy/tests build/pkg/*.dist-info
cp -r ww_vision lambda_function.py build/pkg/
cp models/mobilenetv2_features.onnx models/face_detection_yunet_2023mar.onnx models/head.npz build/pkg/models/
find build/pkg -name __pycache__ -prune -exec rm -rf {} +
"$PY" - <<'EOF'
import os, zipfile
with zipfile.ZipFile("build/ww-vision.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk("build/pkg"):
        for f in files:
            p = os.path.join(root, f)
            z.write(p, os.path.relpath(p, "build/pkg"))
size = sum(i.file_size for i in zipfile.ZipFile("build/ww-vision.zip").infolist())
print(f"unzipped {size / 1e6:.0f} MB (Lambda limit 250 MB)")
assert size < 250e6
EOF
aws s3 cp build/$NAME.zip "s3://$BUCKET/builds/$NAME.zip" --region "$REGION" >/dev/null

echo "== Lambda $NAME"
ENV="Variables={WW_BUCKET=$BUCKET,WW_TABLE=$TABLE,WW_VISION_KEY=$WW_VISION_KEY}"
if aws lambda get-function --function-name "$NAME" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$NAME" --region "$REGION" \
    --s3-bucket "$BUCKET" --s3-key "builds/$NAME.zip" >/dev/null
  aws lambda wait function-updated --function-name "$NAME" --region "$REGION"
  aws lambda update-function-configuration --function-name "$NAME" --region "$REGION" \
    --environment "$ENV" --memory-size 2048 --timeout 30 >/dev/null
else
  aws lambda create-function --function-name "$NAME" --region "$REGION" --runtime python3.12 --architectures x86_64 \
    --handler lambda_function.handler --role "$ROLE_ARN" --memory-size 2048 --timeout 30 \
    --code "S3Bucket=$BUCKET,S3Key=builds/$NAME.zip" --environment "$ENV" >/dev/null
fi
aws lambda wait function-updated --function-name "$NAME" --region "$REGION"
if ! aws lambda get-function-url-config --function-name "$NAME" --region "$REGION" >/dev/null 2>&1; then
  # The URL is public; every route checks the X-WW-Key secret (lambda_function.handler).
  aws lambda create-function-url-config --function-name "$NAME" --region "$REGION" --auth-type NONE >/dev/null
  aws lambda add-permission --function-name "$NAME" --region "$REGION" --statement-id public-url \
    --action lambda:InvokeFunctionUrl --principal '*' --function-url-auth-type NONE >/dev/null
  aws lambda add-permission --function-name "$NAME" --region "$REGION" --statement-id public-url-invoke \
    --action lambda:InvokeFunction --principal '*' --invoked-via-function-url >/dev/null 2>&1 || true
fi
aws logs put-retention-policy --log-group-name "/aws/lambda/$NAME" --retention-in-days 30 --region "$REGION" 2>/dev/null || true

echo "== CloudWatch dashboard"
aws cloudwatch put-dashboard --region "$REGION" --dashboard-name WorthyWaste-Vision --dashboard-body "$(sed "s/{{REGION}}/$REGION/g; s/{{NAME}}/$NAME/g" dashboard.json)" >/dev/null

URL=$(aws lambda get-function-url-config --function-name "$NAME" --region "$REGION" --query FunctionUrl --output text)
echo "WW_VISION_URL=$URL"
