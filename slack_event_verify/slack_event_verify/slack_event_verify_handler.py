# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
Slack event verify handler module for AWS Lambda.

This module provides the Lambda handler function for verifying Slack events
and routing them to the appropriate processing queue.
'''

from __future__ import annotations

import json
import logging
import os
import traceback
from typing import Any

from sqs_wrapper import SqsWrapper
from secrets_manager_wrapper import SecretsManagerWrapper
from slack_sdk_wrapper import SlackSdkWrapper

from .slack_event_verifier import SlackEventVerifier

SIGNING_SECRET_ID = os.environ['SIGNING_SECRET_ID']
SQS_QUEUE_URL = os.environ['SQS_QUEUE_URL']
SLACK_TOKEN_ID = os.getenv('SLACK_TOKEN_ID')

logger = logging.getLogger()
logger.setLevel(level=logging.INFO)

sqs_wrapper = SqsWrapper()
secrets_manager_wrapper = SecretsManagerWrapper()


def verify(event_: dict, _: Any) -> dict:
    '''
    Lambda handler function for verifying Slack events.

    Args:
        event_: The Lambda event dictionary containing the Slack request.
        _: The Lambda context (unused).

    Returns:
        A response dictionary with status code, headers, and body.
    '''
    logger.info(f'Received event: {event_}')

    slack_token = None
    if SLACK_TOKEN_ID:
        slack_token = secrets_manager_wrapper.get_secret(SLACK_TOKEN_ID)

    slack_sdk_wrapper = SlackSdkWrapper(slack_token=slack_token)

    verifier = SlackEventVerifier(
        slack_sdk_wrapper,
        secrets_manager_wrapper,
        sqs_wrapper,
        SIGNING_SECRET_ID,
        SQS_QUEUE_URL,
    )

    try:
        return verifier.verify(event_)
    except:  # pylint: disable=bare-except
        logger.error(f'Error verifying Slack event: {traceback.format_exc()}')
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'message': 'Internal Server Error'}),
        }
