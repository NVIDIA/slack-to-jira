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

'''
Slack event process handler module for AWS Lambda.

This module provides the Lambda handler function for processing Slack events
and managing Jira integration through the SlackEventProcessor.
'''

from __future__ import annotations

import json
import logging
import os
from typing import Any

import event

from dynamodb_wrapper import DynamoDbWrapper
from jira_wrapper import JiraWrapper
from slack_sdk_wrapper import SlackSdkWrapper
from secrets_manager_wrapper import SecretsManagerWrapper

from .slack_event_processor import SlackEventProcessor


logger = logging.getLogger()
logger.setLevel(level=logging.INFO)

dynamo_db_table_name = os.environ['DYNAMODB_TABLE_NAME']
dynamo_db_wrapper = DynamoDbWrapper(dynamo_db_table_name)

secrets_manager_wrapper = SecretsManagerWrapper()

JIRA_TOKEN_ID = os.environ['JIRA_TOKEN_ID']
JIRA_SERVER_URL = os.getenv('JIRA_SERVER_URL')

SLACK_TOKEN_ID = os.environ['SLACK_TOKEN_ID']


def process(event_: dict, _: Any) -> None:
    '''
    Lambda handler function for processing Slack events.

    Args:
        event_: The Lambda event dictionary containing SQS records.
        _: The Lambda context (unused).
    '''
    logger.info(f'Processing event: {event_}')

    jira_token = secrets_manager_wrapper.get_secret(JIRA_TOKEN_ID)
    slack_token = secrets_manager_wrapper.get_secret(SLACK_TOKEN_ID)

    slack_sdk_wrapper = SlackSdkWrapper(slack_token)
    jira_wrapper = JiraWrapper(JIRA_SERVER_URL, jira_token)

    event_factory = event.EventFactory(
        slack_sdk_wrapper,
        jira_wrapper,
        dynamo_db_wrapper,
    )

    processor = SlackEventProcessor(event_factory)

    # TODO handle multiple records
    return processor.process(json.loads(event_['Records'][0]['body'])['event'])
