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

resource "aws_cloudwatch_metric_alarm" "slack_event_verify_lambda_invocations" {
  alarm_name        = "${local.project_name}-slack-event-verify-lambda-invocations${local.suffix}"
  alarm_description = "This alarm monitors the number of invocations in the slack event verify lambda for ${local.project_name}."

  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Invocations"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 20

  dimensions = {
    FunctionName = aws_lambda_function.verify_lambda.function_name
  }

  alarm_actions      = [var.sns_alert_topic_arn]
  ok_actions         = [var.sns_alert_topic_arn]
  treat_missing_data = "ignore"
  tags = {
    Name = "${local.project_name}-slack-event-verify-lambda-invocations${local.suffix}"
  }
}
resource "aws_cloudwatch_metric_alarm" "slack_event_process_lambda_invocations" {
  alarm_name        = "${local.project_name}-slack-event-process-lambda-invocations${local.suffix}"
  alarm_description = "This alarm monitors the number of invocations in the slack event process lambda for ${local.project_name}."

  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Invocations"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 20

  dimensions = {
    FunctionName = aws_lambda_function.process_lambda.function_name
  }

  alarm_actions      = [var.sns_alert_topic_arn]
  ok_actions         = [var.sns_alert_topic_arn]
  treat_missing_data = "ignore"

  tags = {
    Name = "${local.project_name}-slack-event-process-lambda-invocations${local.suffix}"
  }
}

resource "aws_cloudwatch_metric_alarm" "slack_event_dlq_message_count" {
  alarm_name          = "${local.project_name}-dlq-message-count${local.suffix}"
  alarm_description   = "This alarm monitor the number of message in the DLQ for ${local.project_name}."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Average"
  threshold           = 10

  dimensions = {
    QueueName = aws_sqs_queue.main_dlq.name
  }

  alarm_actions      = [var.sns_alert_topic_arn]
  ok_actions         = [var.sns_alert_topic_arn]
  treat_missing_data = "ignore"
  tags = {
    Name = "${local.project_name}-dlq-message-count${local.suffix}"
  }
}