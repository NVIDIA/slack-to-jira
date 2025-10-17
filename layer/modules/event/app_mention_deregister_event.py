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
App mention deregister event module for unlinking Slack threads from Jira issues.

This module provides the AppMentionDeregisterEvent class that handles the
"deregister" command, removing links between Slack threads and Jira issues.
'''

from __future__ import annotations

import logging
from typing import Any

from .app_mention_event import AppMentionEvent
from .exceptions import IgnorableException
from .event_factory import EventFactory

logger = logging.getLogger()


class AppMentionDeregisterEvent(AppMentionEvent):
    '''
    Event handler for deregistering Slack threads from Jira issues.

    This event is triggered when users mention the bot with the "deregister" command:
        @bot deregister PROJ-123

    The command removes the bidirectional link:
    - Removes the remote link from Jira
    - Deletes the mapping from DynamoDB

    Unlike register, deregister requires an exact match and only takes the
    Jira issue ID (no optional parameters).

    Attributes:
        name: The command name ('deregister').
        sanitized_text: The command arguments after sanitization.
    '''

    name: str = 'deregister'

    def _handle_event_sub_type(self, args: Any) -> None:
        '''
        Extract and validate the deregister command arguments.

        Sanitizes the arguments by stripping whitespace and handling None values.
        Unlike register, deregister only accepts a single argument (Jira issue ID).

        Args:
            args: The raw command arguments after the "deregister" command.
                  Expected format: "PROJ-123" (no additional parameters allowed)

        Sets:
            self.sanitized_text: The trimmed argument string, or empty if invalid.
        '''
        self.sanitized_text = args.strip() if isinstance(args, str) else ''

    def _process_event(self) -> None:
        '''
        Deregister a Slack thread from a Jira issue.

        This method implements the core deregistration logic:
        1. Parse command arguments to extract Jira issue ID (must be exactly one arg)
        2. Look up the registration in DynamoDB
        3. Verify the registration exists
        4. Remove the remote link from Jira (best effort)
        5. Delete the registration from DynamoDB

        The method is strict about validation:
        - Requires exactly one argument (Jira issue ID)
        - Requires existing registration in DynamoDB
        - Requires valid jira_link_id in the registration

        If the Jira link removal fails (e.g., already deleted), the method logs
        a warning but continues to delete the DynamoDB entry to maintain consistency.

        Raises:
            IgnorableException: If command format is invalid, registration doesn't exist,
                              or jira_link_id is missing from registration.
        '''
        if not self.sanitized_text:
            logger.error(f'Invalid command format in app mention event: {self.sanitized_text}')
            raise IgnorableException(
                f'Invalid command format in app mention event: {self.sanitized_text}'
            )

        if self.dynamo_db_wrapper is None:
            raise IgnorableException(
                f'No dynamo_db_wrapper found for message {self.message_ts} '
                f'in channel {self.channel_id}'
            )

        if self.jira_wrapper is None:
            raise IgnorableException(
                f'No jira_wrapper found for message {self.message_ts} '
                f'in channel {self.channel_id}'
            )

        command_parts = self.sanitized_text.split(' ')
        if len(command_parts) != 1:
            logger.error(f'Invalid command format in app mention event: {self.sanitized_text}')
            raise IgnorableException(
                f'Invalid command format in app mention event: {self.sanitized_text}'
            )

        jira_issue_id = command_parts[0]

        thread_id = self._get_thread_id(self.thread_ts, self.channel_id)  # type: ignore
        dynamodb_key = {
            'jira_issue_id': jira_issue_id,
            'slack_thread_id': thread_id,
        }

        channel_name = self.slack_sdk_wrapper.get_channel_name(self.channel_id)  # type: ignore
        item = self.dynamo_db_wrapper.get_item(dynamodb_key)

        if item is None:
            raise IgnorableException(
                f'Jira issue {jira_issue_id} not registered to thread '
                f'{thread_id} in channel {channel_name}'
            )

        jira_link_id = item.get('jira_link_id')
        if not jira_link_id:
            raise IgnorableException(
                f'No jira link information for dynamodb item ' f'with key {dynamodb_key}'
            )

        try:
            self.jira_wrapper.remove_link(jira_issue_id, jira_link_id)
        except Exception as e:
            logger.warning(
                f'Was not able to remove jira link {jira_link_id} for {jira_issue_id}. '
                f' Exception: {e}'
            )

        self.dynamo_db_wrapper.delete_item(dynamodb_key)
        logger.info(
            f'Jira issue {jira_issue_id} deregistered from thread '
            f'{thread_id} in channel {channel_name}'
        )


# Register this concrete event type with the factory for command routing
EventFactory.concrete_event_types[AppMentionDeregisterEvent.name] = AppMentionDeregisterEvent
