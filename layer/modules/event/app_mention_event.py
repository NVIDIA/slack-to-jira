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
App mention event module for handling Slack app mentions.

This module provides the AppMentionEvent class that processes events triggered
when users mention the bot in Slack channels using @bot_name.
'''

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from .event import Event
from .event_factory import EventFactory
from .exceptions import NotHandledException

logger = logging.getLogger()


class AppMentionEvent(Event):
    '''
    Event handler for Slack app_mention events.

    This class processes events when users mention the bot in Slack messages.
    It parses the mention text to extract commands and arguments, then routes
    to concrete subclasses (e.g., register, deregister) based on the command.

    The class serves as an intermediate abstract class in the event hierarchy:
    Event -> AppMentionEvent -> AppMentionRegisterEvent/AppMentionDeregisterEvent

    Attributes:
        name: The Slack event type name ('app_mention').
        thread_ts: The thread timestamp where the mention occurred.
        channel_id: The channel ID where the mention occurred.
        message_ts: The message timestamp of the mention.
    '''

    name: str = 'app_mention'

    thread_ts: Optional[str] = None
    channel_id: Optional[str] = None
    message_ts: Optional[str] = None

    @staticmethod
    def _sanitize_command_text(text: Optional[str]) -> str:
        '''
        Remove user mentions from command text.

        Strips out Slack user mention syntax (e.g., <@U12345>) from the message
        text to extract the actual command and arguments. This allows processing
        messages like "@bot register PROJ-123" -> "register PROJ-123".

        Args:
            text: The original text containing user mentions. May be None.

        Returns:
            The sanitized text with all user mentions removed and whitespace trimmed.
            Returns empty string if text is None.

        Example:
            >>> _sanitize_command_text("<@U123> register PROJ-123")
            "register PROJ-123"
        '''
        if text is None:
            return ''

        replace_patterns = (
            (r'<@[^>]+>', r''),  # Remove user mentions
            (r'<https?:\/\/[^>|]+?\|([^>]+)>', r'\1'),  # Replace link+text with just text
            (r'<(https?:\/\/[^>]+)>', r'\1'),  # Replace bare links with the raw actual link text
            (r'\s{2,}', ' '),  # Remove duplicate spaces
        )

        for pattern, replace in replace_patterns:
            text = re.sub(pattern, replace, text)

        return text.strip()

    @classmethod
    def infer_subtype(cls, event_data: dict) -> tuple[str, Any]:
        '''
        Infer the command type from the app mention text.

        Parses the sanitized mention text to extract the command (first word)
        and any remaining arguments. The command determines which concrete event
        class will handle the request (e.g., "register" -> AppMentionRegisterEvent).

        Args:
            event_data: The Slack event dictionary containing the 'text' field.

        Returns:
            A tuple of (command, args) where:
                - command: The first word after sanitization (e.g., "register", "deregister")
                - args: Remaining text after the command, or None if no arguments

        Example:
            For "@bot register PROJ-123 My Feature":
                Returns: ("register", "PROJ-123 My Feature")

            For "@bot deregister PROJ-123":
                Returns: ("deregister", "PROJ-123")
        '''
        text = cls._sanitize_command_text(event_data.get('text', ''))

        sub_event_type, args = (text.split(' ', maxsplit=1) + [None])[:2]
        return sub_event_type, args  # type: ignore[return-value]

    def _handle_event_type(self, event_data: dict) -> None:
        '''
        Extract and validate app_mention event data.

        Parses the Slack app_mention event to extract required fields:
        thread_ts, channel_id, and message_ts. All three fields are required
        for app mention events to be processed.

        For app mentions, the thread_ts is critical as it identifies which
        conversation thread to link with Jira issues. If the mention is in
        a thread, thread_ts is provided; if it's a top-level message, thread_ts
        equals message_ts.

        Args:
            event_data: The Slack event dictionary containing app_mention data.

        Raises:
            NotHandledException: If any required field (thread_ts, channel, ts) is missing.

        Sets:
            self.thread_ts: The thread timestamp for the conversation.
            self.channel_id: The Slack channel ID where mention occurred.
            self.message_ts: The timestamp of the mention message.
        '''
        logger.info(f'Processing app mention event: {event_data}')

        self.thread_ts = event_data.get('thread_ts')

        self.channel_id = event_data.get('channel')
        self.message_ts = event_data.get('ts')

        if self.thread_ts is None:
            logger.error(f'Missing thread_ts in app mention event: {event_data}')
            raise NotHandledException(f'Missing thread_ts in app mention event: {event_data}')

        if self.channel_id is None:
            logger.error(f'Missing channel in app mention event: {event_data}')
            raise NotHandledException(f'Missing channel in app mention event: {event_data}')

        if self.message_ts is None:
            logger.error(f'Missing message_ts in app mention event: {event_data}')
            raise NotHandledException(f'Missing message_ts in app mention event: {event_data}')

    def construct_message_group_id(self) -> str:
        '''
        Construct a message group ID based on the event type.
        '''
        return '_'.join((self.channel_id, self.thread_ts))  # type: ignore


# Register this event type with the factory for automatic routing
EventFactory.top_level_event_types[AppMentionEvent.name] = (
    AppMentionEvent  # type: ignore[type-abstract]
)
