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

# In this case, the slack_thread_id must be a combination of the
# thread_ts and the channel_id to enforce uniqueness.
resource "aws_dynamodb_table" "dynamodb_table" {
  name         = "${local.project_name}-dynamodb-table${local.suffix}"
  billing_mode = "PAY_PER_REQUEST"

  attribute {
    name = "slack_thread_id"
    type = "S"
  }

  attribute {
    name = "jira_issue_id"
    type = "S"
  }

  hash_key  = "slack_thread_id"
  range_key = "jira_issue_id"

  tags = {
    Name = "${local.project_name}-dynamodb-table${local.suffix}"
  }
}