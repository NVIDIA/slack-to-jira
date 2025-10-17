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

resource "aws_iam_policy" "process_lambda_policy" {
  name = "${local.project_name}-process-lambda-policy${local.suffix}"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
        ]
        Resource = aws_dynamodb_table.dynamodb_table.arn
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow",
        Action = [
          "secretsmanager:GetSecretValue",
        ]
        Resource = [
          aws_secretsmanager_secret.jira_token.arn,
          aws_secretsmanager_secret.slack_token.arn,
        ]
      },
      {
        Effect = "Allow",
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
        ]
        Resource = aws_sqs_queue.main_queue.arn
      }
    ]
  })
  tags = {
    Name = "${local.project_name}-process-lambda-policy${local.suffix}"
  }
}

data "aws_iam_policy_document" "process_lambda_policy_document" {
  statement {
    actions = ["sts:AssumeRole"]
    effect  = "Allow"
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "process_lambda_role" {
  name               = "${local.project_name}-process-lambda-role${local.suffix}"
  assume_role_policy = data.aws_iam_policy_document.process_lambda_policy_document.json

  tags = {
    Name = "${local.project_name}-process-lambda-role${local.suffix}"
  }
}

resource "aws_iam_role_policy_attachment" "process_lambda_policy_attachment" {
  role       = aws_iam_role.process_lambda_role.name
  policy_arn = aws_iam_policy.process_lambda_policy.arn
}

data "archive_file" "process_lambda_archive" {
  type        = "zip"
  source_dir  = "slack_event_process"
  output_path = "slack_event_process.zip"
}

resource "aws_lambda_function" "process_lambda" {
  function_name = "${local.project_name}-process-lambda${local.suffix}"
  description   = "Lambda to process valid slack events."
  role          = aws_iam_role.process_lambda_role.arn
  handler       = "slack_event_process.slack_event_process_handler.process"
  runtime       = "python3.13"
  architectures = ["arm64"]

  filename         = data.archive_file.process_lambda_archive.output_path
  source_code_hash = data.archive_file.process_lambda_archive.output_base64sha256

  layers = [aws_lambda_layer_version.layer.arn]

  timeout     = 60
  memory_size = 1024
  environment {
    variables = {
      DYNAMODB_TABLE_NAME = aws_dynamodb_table.dynamodb_table.name
      JIRA_TOKEN_ID       = aws_secretsmanager_secret.jira_token.id
      JIRA_SERVER_URL     = var.jira_server_url
      SLACK_TOKEN_ID      = aws_secretsmanager_secret.slack_token.id
    }
  }

  tags = {
    Name = "${local.project_name}-process-lambda${local.suffix}"
  }
}
resource "aws_lambda_event_source_mapping" "process_lambda_source_mapping" {
  event_source_arn = aws_sqs_queue.main_queue.arn
  function_name    = aws_lambda_function.process_lambda.arn
  enabled          = true
  batch_size       = 1


  tags = {
    Name = "${local.project_name}-process-lambda-source-mapping${local.suffix}"
  }
}

resource "aws_cloudwatch_log_group" "process_lambda_log_group" {
  name = "/aws/lambda/${aws_lambda_function.process_lambda.function_name}"

  retention_in_days = 30

  tags = {
    Name = "${aws_lambda_function.process_lambda.function_name}-log-group"
  }
}