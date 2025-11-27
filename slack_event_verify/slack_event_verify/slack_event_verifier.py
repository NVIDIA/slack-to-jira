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
Slack event verifier module for handling Slack event verification and routing.

This module provides functionality to verify Slack requests, handle URL verification
challenges, and route events to appropriate processing queues.
'''

from __future__ import annotations

import base64
import json
import logging

from typing import TYPE_CHECKING

import event

if TYPE_CHECKING:
    from slack_sdk_wrapper import SlackSdkWrapper
    from secrets_manager_wrapper import SecretsManagerWrapper
    from sqs_wrapper import SqsWrapper

logger = logging.getLogger(__name__)


class SlackEventVerifier:  # pylint: disable=too-few-public-methods
    '''
    A verifier for handling Slack event verification and routing.

    This class verifies Slack requests, handles URL verification challenges,
    and routes events to appropriate processing queues.
    '''

    URL_VERIFICATION_EVENT_TYPE = 'url_verification'

    def __init__(
        self,
        slack_sdk_wrapper: SlackSdkWrapper,  # pylint: disable=undefined-variable
        secrets_manager_wrapper: SecretsManagerWrapper,  # pylint: disable=undefined-variable
        sqs_wrapper: SqsWrapper,  # pylint: disable=undefined-variable
        signing_secret_id: str,
        sqs_queue_url: str,
    ) -> None:
        '''
        Initialize the Slack event verifier.

        Args:
            slack_sdk_wrapper: The Slack SDK wrapper instance.
            secrets_manager_wrapper: The secrets manager wrapper instance.
            sqs_wrapper: The SQS wrapper instance.
            signing_secret_id: The ID of the signing secret in secrets manager.
            sqs_queue_url: The URL of the SQS queue for event processing.
        '''
        self.slack_sdk_wrapper = slack_sdk_wrapper
        self.secrets_manager_wrapper = secrets_manager_wrapper
        self.sqs_wrapper = sqs_wrapper
        self.signing_secret_id = signing_secret_id
        self.sqs_queue_url = sqs_queue_url

    def verify(self, event_dict: dict) -> dict:
        '''
        Verify and process a Slack event.

        Args:
            event_dict: The Lambda event dictionary containing headers and body.

        Returns:
            A response dictionary with status code, headers, and body.
        '''
        headers = event_dict.get('headers', {})
        body = event_dict.get('body', {})
        if event_dict.get('isBase64Encoded', False):
            body = base64.b64decode(body).decode('utf-8')

        if not body or not headers:
            logger.error(f'Missing headers or body: {event_dict}')
            return self.construct_return_data(400, 'application/json', {'message': 'Bad Request'})

        signing_secret = self.secrets_manager_wrapper.get_secret(self.signing_secret_id)

        if not self.slack_sdk_wrapper.is_valid_request(body, headers, signing_secret):
            logger.error(f'Could not verify request: {event_dict}')
            return self.construct_return_data(403, 'application/json', {'message': 'Forbidden'})

        body = json.loads(body)

        logger.info(f'Authenticated Slack event: {body}')

        # Synchronous invocation.
        # Return the challenge to Slack for verification.
        if body.get('type') == 'url_verification':
            logger.info(f'Returning challenge to Slack: {body}')
            return {
                'statusCode': 200,
                'headers': {'Content-Type': 'text/plain'},
                'body': body.get('challenge'),
            }

        event_dict = body.get('event', {})

        try:
            # We don't need to pass in the wrappers.
            # We are only interested in forming a valid event here.
            # We don't want to handle it in the verifier.
            event_obj = event.EventFactory(self.slack_sdk_wrapper, None, None).create_event(
                event_dict
            )
        except event.EventFactory.UndefinedCommand:
            logger.error(f'Unsupported event: {event_dict}')
            return self.construct_return_data(400, 'application/json', {'message': 'Bad Request'})

        # Asynchronous handling.
        # Send the event to the SQS queue and forget about it.
        # TODO handle rate limit errors
        logger.info(f'Sending event to SQS queue {self.sqs_queue_url}: {body}')
        self.sqs_wrapper.send_message(
            queue_url=self.sqs_queue_url,
            message=body,
            message_group_id=event_obj.construct_message_group_id(),
        )

        return self.construct_return_data(200, 'application/json', {'message': 'Success'})

    @staticmethod
    def construct_return_data(status_code: int, content_type: str, body: dict) -> dict:
        '''
        Construct a return data dictionary.
        '''
        return {
            'statusCode': status_code,
            'headers': {'Content-Type': content_type},
            'body': json.dumps(body),
        }
