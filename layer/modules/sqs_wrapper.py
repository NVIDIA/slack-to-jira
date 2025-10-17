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
SQS wrapper module for simplified SQS operations.

This module provides a simplified interface for common SQS operations
including sending messages to queues with optional message grouping.
'''

from __future__ import annotations

import json

import boto3


class SqsWrapper:  # pylint: disable=too-few-public-methods
    '''
    A wrapper class for SQS operations.

    This class provides a simplified interface for common SQS operations
    including sending messages to queues with optional message grouping.
    '''

    def __init__(self) -> None:
        self.sqs_client = boto3.client('sqs')

    def send_message(self, queue_url: str, message: str | dict, message_group_id: str) -> None:
        '''
        Send a message to an SQS queue.

        Args:
            queue_url: The URL of the SQS queue to send the message to.
            message: The message to send. Can be a string or any JSON-serializable object.
            message_group_id: Message group ID for FIFO queues.
        '''
        if not isinstance(message, str):
            message = json.dumps(message)

        self.sqs_client.send_message(
            QueueUrl=queue_url,
            MessageBody=message,
            MessageGroupId=message_group_id,
        )
