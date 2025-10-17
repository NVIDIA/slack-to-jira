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

variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-west-1"
}

variable "dev_environment" {
  type        = bool
  description = "Whether to deploy to the dev environment"
  default     = true
}

variable "jira_token" {
  type        = string
  description = "Jira token for the Slack to Jira integration"
}

variable "slack_token" {
  type        = string
  description = "Slack token for requests to the Slack API"
}

variable "slack_signing_secret" {
  type        = string
  description = "Slack signing secret for requests to the Slack API"
}

variable "sns_alert_topic_arn" {
  type        = string
  description = "SNS alert topic ARN"
}

variable "tick_reaction" {
  type = string
}

variable "x_reaction" {
  type = string
}

variable "sync_reaction" {
  type = string
}

variable "icon_url" {
  type = string
}

variable "icon_title" {
  type = string
}

variable "jira_server_url" {
  type = string
}

variable "app_name" {
  type = string
}

variable "owner" {
  type = string
}
