# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

resource "aws_iam_policy" "verify_lambda_policy" {
  name = "${local.project_name}-verify-lambda-policy${local.suffix}"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.main_queue.arn
      },
      {
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = aws_secretsmanager_secret.slack_signing_secret.arn
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      }
    ]
  })
}

data "aws_iam_policy_document" "verify_lambda_policy_document" {
  statement {
    actions = ["sts:AssumeRole"]
    effect  = "Allow"
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "verify_lambda_role" {
  name               = "${local.project_name}-verify-lambda-role${local.suffix}"
  assume_role_policy = data.aws_iam_policy_document.verify_lambda_policy_document.json

  tags = {
    Name = "${local.project_name}-verify-lambda-role${local.suffix}"
  }
}

resource "aws_iam_role_policy_attachment" "verify_lambda_policy_attachment" {
  role       = aws_iam_role.verify_lambda_role.name
  policy_arn = aws_iam_policy.verify_lambda_policy.arn
}

data "archive_file" "verify_lambda_archive" {
  type        = "zip"
  source_dir  = "slack_event_verify"
  output_path = "slack_event_verify.zip"
}

resource "aws_lambda_function" "verify_lambda" {
  function_name = "${local.project_name}-verify-lambda${local.suffix}"
  description   = "Lambda to verify valid slack events."
  runtime       = "python3.13"
  architectures = ["arm64"]
  handler       = "slack_event_verify.slack_event_verify_handler.verify"

  filename         = data.archive_file.verify_lambda_archive.output_path
  source_code_hash = data.archive_file.verify_lambda_archive.output_base64sha256

  layers = [aws_lambda_layer_version.layer.arn]

  memory_size = 1024
  timeout     = 3

  role = aws_iam_role.verify_lambda_role.arn

  environment {
    variables = {
      SQS_QUEUE_URL     = aws_sqs_queue.main_queue.id
      SIGNING_SECRET_ID = aws_secretsmanager_secret.slack_signing_secret.id
    }
  }

  tags = {
    Name = "${local.project_name}-verify-lambda${local.suffix}"
  }
}

resource "aws_cloudwatch_log_group" "verify_lambda_log_group" {
  name = "/aws/lambda/${aws_lambda_function.verify_lambda.function_name}"

  retention_in_days = 30

  tags = {
    Name = "${aws_lambda_function.verify_lambda.function_name}-log-group"
  }
}