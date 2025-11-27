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
App mention register event module for linking Slack threads to Jira issues.

This module provides the AppMentionRegisterEvent class that handles the
"register" command, creating or updating links between Slack threads and
Jira issues.
'''

from __future__ import annotations

from datetime import datetime, UTC
import logging
from typing import Any, Optional, cast

from .app_mention_event import AppMentionEvent
from .event_factory import EventFactory
from .exceptions import IgnorableException
from .config import CONFIG

logger = logging.getLogger()


class AppMentionRegisterEvent(AppMentionEvent):
    '''
    Event handler for registering Slack threads to Jira issues.

    This event is triggered when users mention the bot with the "register" command:
        @bot register PROJ-123 [optional custom link text]

    The command creates a bidirectional link:
    - Adds a remote link in Jira pointing to the Slack thread
    - Stores the mapping in DynamoDB for future comment syncing

    If the registration already exists, it updates the link title instead of
    creating a duplicate.

    Attributes:
        name: The command name ('register').
        icon_url: URL of the icon to display in Jira links.
        icon_title: Title text for the icon in Jira links.
        sanitized_text: The command arguments after sanitization.
        jira_issue_id: The Jira issue ID to link (e.g., "PROJ-123").
        optional_param: Optional custom text for the link title.
        thread_link: The permalink to the Slack thread.
        link_title: The formatted title for the Jira remote link.
    '''

    name: str = 'register'

    icon_url: str = CONFIG['icon_url']
    icon_title: str = CONFIG['icon_title']
    app_name: str = CONFIG['app_name']

    sanitized_text: Optional[str] = None

    def _handle_event_sub_type(self, args: Any) -> None:
        '''
        Extract and validate the command arguments.

        Sanitizes the arguments by stripping whitespace and handling None values.
        The sanitized text will be further parsed in _process_event to extract
        the Jira issue ID and optional parameters.

        Args:
            args: The raw command arguments after the "register" command.
                  Expected format: "PROJ-123" or "PROJ-123 Custom Link Text"

        Sets:
            self.sanitized_text: The trimmed argument string, or empty if invalid.
        '''
        self.sanitized_text = args.strip() if isinstance(args, str) else ''

    def _process_event(self) -> None:
        '''
        Register a Slack thread to a Jira issue with link management.

        This method implements the core registration logic:
        1. Parse command arguments to extract Jira issue ID
        2. Check if registration already exists in DynamoDB
        3. Verify if existing Jira remote link is still valid
        4. Update existing link or create new link as appropriate
        5. Store/update registration in DynamoDB

        The method handles three scenarios:
        - New registration: Creates link in Jira and DynamoDB entry
        - Existing valid registration: Updates the link title in Jira
        - Existing invalid registration: Creates new link, updates DynamoDB

        Raises:
            IgnorableException: If command format is invalid (no Jira issue ID provided).
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

        command_parts = self.sanitized_text.split(' ', maxsplit=1)
        logger.info(f'Command parts: {command_parts}, sanitized text: {self.sanitized_text}')
        if len(command_parts) < 1:
            logger.error(f'Invalid command format in app mention event: {self.sanitized_text}')
            raise IgnorableException(
                f'Invalid command format in app mention event: {self.sanitized_text}'
            )

        jira_issue_id, optional_param = (command_parts + [None])[:2]
        link_text = optional_param or self.thread_ts
        channel_name = self.slack_sdk_wrapper.get_channel_name(self.channel_id)  # type: ignore # pylint: disable=line-too-long
        thread_link = self.slack_sdk_wrapper.get_message_link(self.channel_id, self.thread_ts)  # type: ignore # pylint: disable=line-too-long
        link_title = self._get_link_title(channel_name, link_text)  # type: ignore

        thread_id = self._get_thread_id(self.thread_ts, self.channel_id)  # type: ignore
        dynamodb_key = {
            'jira_issue_id': jira_issue_id,
            'slack_thread_id': thread_id,
        }

        existing_item = self.dynamo_db_wrapper.get_item(dynamodb_key)

        remote_link_valid = False
        if existing_item:
            jira_link_id = existing_item.get('jira_link_id')
            if jira_link_id:
                remote_link_valid = self.jira_wrapper.validate_link(jira_issue_id, jira_link_id)  # type: ignore # pylint: disable=line-too-long
        else:
            existing_item = {}

        # There are 3 main cases here:
        # 1. The item exists and the link is still valid.
        # 2. The item exists and the link is no longer valid.
        # 3. The item does not exist.

        if existing_item and remote_link_valid:
            logger.info(
                f'Thread {thread_id} already registered to Jira issue {jira_issue_id}'
                'Updating link text...'
            )
            self.jira_wrapper.update_link(
                cast(str, jira_issue_id),
                cast(str, jira_link_id),
                thread_link,
                link_title,
            )
        else:
            if existing_item:
                logger.info(
                    f'Thread {thread_id} already registered to Jira issue {jira_issue_id}'
                    'but link is no longer valid. Creating a new link...'
                )

            jira_link_id = self.jira_wrapper.add_link(
                jira_issue_id,  # type: ignore
                thread_link,
                link_title,
                self.icon_url,
                self.icon_title,
            )

        # With duplicates, the last one is kept.
        item = {
            **dynamodb_key,
            **existing_item,
            'created_at': datetime.now(UTC).isoformat(),
            'jira_link_id': str(jira_link_id),
        }

        self.dynamo_db_wrapper.put_item(item)
        logger.info(
            f'Jira issue {jira_issue_id} registered to thread '
            f'{thread_id} in channel {self.channel_id}'
        )

    @staticmethod
    def _get_link_title(channel_name: str, link_text: str) -> str:
        '''
        Format the title for the Jira remote link.

        Creates a standardized title format that includes the bot name,
        the Slack channel name, and custom link text or thread timestamp.

        Args:
            channel_name: The name of the Slack channel (without #).
            link_text: Custom link text or thread timestamp.

        Returns:
            Formatted link title string (e.g., "<app_name>: #general 1234567890.123456").
        '''
        return f'{AppMentionRegisterEvent.app_name}: #{channel_name} {link_text}'


# Register this concrete event type with the factory for command routing
EventFactory.concrete_event_types[AppMentionRegisterEvent.name] = AppMentionRegisterEvent
