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

resource "aws_secretsmanager_secret" "jira_token" {
  name                    = "${local.project_name}-jira-token${local.suffix}"
  description             = "Jira token for the Slack to Jira integration."
  recovery_window_in_days = 0
  tags = {
    Name = "${local.project_name}-jira-token${local.suffix}"
  }
}

resource "aws_secretsmanager_secret" "slack_token" {
  name        = "${local.project_name}-slack-token${local.suffix}"
  description = "Slack token for requests to the Slack API."

  recovery_window_in_days = 0
  tags = {
    Name = "${local.project_name}-slack-token${local.suffix}"
  }
}

resource "aws_secretsmanager_secret" "slack_signing_secret" {
  name        = "${local.project_name}-slack-signing-secret${local.suffix}"
  description = "Slack signing secret for request verification."

  recovery_window_in_days = 0
  tags = {
    Name = "${local.project_name}-slack-signing-secret${local.suffix}"
  }
}

resource "aws_secretsmanager_secret_version" "jira_token_version" {
  secret_id     = aws_secretsmanager_secret.jira_token.id
  secret_string = var.jira_token
}

resource "aws_secretsmanager_secret_version" "slack_token_version" {
  secret_id     = aws_secretsmanager_secret.slack_token.id
  secret_string = var.slack_token
}

resource "aws_secretsmanager_secret_version" "slack_signing_secret_version" {
  secret_id     = aws_secretsmanager_secret.slack_signing_secret.id
  secret_string = var.slack_signing_secret
}

