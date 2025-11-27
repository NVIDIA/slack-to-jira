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

resource "aws_sqs_queue" "main_queue" {
  name = "${local.project_name}-queue${local.suffix}.fifo"

  fifo_queue                  = true
  content_based_deduplication = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.main_dlq.arn
    maxReceiveCount     = 1
  })

  visibility_timeout_seconds = 60

  tags = {
    Name = "${local.project_name}-queue"
  }
}

resource "aws_sqs_queue_policy" "main_queue_policy" {
  queue_url = aws_sqs_queue.main_queue.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = aws_iam_role.verify_lambda_role.arn
        }
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.main_queue.arn
      }
    ]
  })
}

resource "aws_sqs_queue" "main_dlq" {
  name = "${local.project_name}-queue-dlq${local.suffix}.fifo"

  fifo_queue                  = true
  content_based_deduplication = true

  message_retention_seconds = 345600

  visibility_timeout_seconds = 60

  tags = {
    Name = "${local.project_name}-queue-dlq"
  }
}

resource "aws_sqs_queue_redrive_allow_policy" "redrive_allow_policy" {
  queue_url = aws_sqs_queue.main_dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue",
    sourceQueueArns   = [aws_sqs_queue.main_queue.arn]
  })
}
