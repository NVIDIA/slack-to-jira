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
Slack SDK wrapper module for simplified Slack operations.

This module provides a simplified interface for common Slack operations
including request validation, event handling, message operations, and reactions.
'''

from __future__ import annotations

from typing import Optional, Iterable, List

from slack_sdk.errors import SlackClientError
from slack_sdk.http_retry.builtin_handlers import (
    RateLimitErrorRetryHandler,
    ConnectionErrorRetryHandler,
)
from slack_sdk.signature import SignatureVerifier
from slack_sdk.web.client import WebClient


# TODO Split into 2 classes or rename class.
class SlackSdkWrapper:
    '''
    A wrapper class for Slack SDK operations.

    This class provides a simplified interface for common Slack operations
    including request validation, event handling, message operations, and reactions.
    '''

    ClientException = SlackClientError

    def __init__(self, slack_token: Optional[str] = None) -> None:
        if slack_token:
            self.client = WebClient(token=slack_token)
            self.bot_id = self.client.auth_test()['user_id']

            self.client.retry_handlers = [
                RateLimitErrorRetryHandler(3),
                ConnectionErrorRetryHandler(3),
            ]

    def is_valid_request(self, body: str, headers: dict, signing_secret: str) -> bool:
        '''
        Validate a Slack request using signature verification.

        Args:
            body: The request body as a string.
            headers: The request headers as a dictionary.
            signing_secret: The Slack app signing secret.

        Returns:
            True if the request is valid, False otherwise.
        '''
        return SignatureVerifier(signing_secret=signing_secret).is_valid_request(
            body=body,
            headers=headers,
        )

    def get_event_channel_id(self, event: dict) -> str:
        '''
        Get the channel ID from a Slack event.

        Args:
            event: The Slack event dictionary.

        Returns:
            The channel ID from the event.

        Raises:
            ValueError: If the event type is not supported.
        '''
        if event.get('type') == 'reaction_added':
            return event['item']['channel']

        if event.get('type') == 'app_mention':
            return event['channel']

        raise ValueError(f'Unhandled event type: {event.get("type")}')

    def get_event_message_ts(self, event: dict) -> str:
        '''
        Get the message timestamp from a Slack event.

        Args:
            event: The Slack event dictionary.

        Returns:
            The message timestamp from the event.

        Raises:
            ValueError: If the event type is not supported.
        '''
        if event.get('type') == 'reaction_added':
            return event['item']['ts']

        if event.get('type') == 'app_mention':
            return event['ts']

        raise ValueError(f'Unhandled event type: {event.get("type")}')

    def get_event_thread_ts(self, event: dict) -> Optional[str]:
        '''
        Get the thread timestamp from a Slack event.

        Args:
            event: The Slack event dictionary.

        Returns:
            The thread timestamp from the event.

        Raises:
            ValueError: If the event type is not supported.
        '''
        if event.get('type') == 'reaction_added':
            return self.get_thread_ts_from_message_ts(
                self.get_event_channel_id(event),
                self.get_event_message_ts(event),
            )

        if event.get('type') == 'app_mention':
            return event['thread_ts']

        raise ValueError(f'Unhandled event type: {event.get("type")}')

    def get_message_link(self, channel_id: str, message_ts: str) -> str:
        '''
        Get a permalink for a Slack message.

        Args:
            channel_id: The ID of the channel containing the message.
            message_ts: The timestamp of the message.

        Returns:
            The permalink URL for the message.
        '''
        return self.client.chat_getPermalink(
            channel=channel_id,
            message_ts=message_ts,
        )['permalink']

    def get_channel_name(self, channel_id: str) -> str:
        '''
        Get the name of a Slack channel.

        Args:
            channel_id: The ID of the channel.

        Returns:
            The name of the channel.
        '''
        return self.client.conversations_info(channel=channel_id)['channel']['name']

    def get_thread_ts_from_message_ts(self, channel_id: str, message_ts: str) -> Optional[str]:
        '''
        Get the thread timestamp from a message timestamp.

        Args:
            channel_id: The ID of the channel containing the message.
            message_ts: The timestamp of the message.

        Returns:
            The thread timestamp if the message is part of a thread, None otherwise.
        '''
        response = self.client.conversations_replies(
            channel=channel_id,
            ts=message_ts,
            limit=1,
        )
        messages: List[dict] = response.get('messages', [])
        if not messages:
            return None

        return messages[0].get('thread_ts')

    def get_content_from_message_ts(
        self, channel_id: str, message_ts: str
    ) -> Optional[tuple[Optional[str], Iterable[dict]]]:
        '''
        Get the text content from a message timestamp.

        Args:
            channel_id: The ID of the channel containing the message.
            message_ts: The timestamp of the message.

        Returns:
            A tuple of (text content of the message, list of file dictionaries)
            or None if the message doesn't exist.
        '''
        response = self.client.conversations_replies(
            channel=channel_id,
            ts=message_ts,
            limit=1,
        )

        messages: List[dict] = response.get('messages', [])
        if not messages:
            return None

        message = messages[0]

        return (
            message.get('text', ''),
            (
                {
                    'name': file.get('name'),
                    'url': file.get('url_private_download'),
                }
                for file in message.get('files', [])
                if file.get('url_private_download')
            ),
        )

    def add_reaction(self, channel_id: str, message_ts: str, reaction: str) -> None:
        '''
        Add a reaction to a Slack message.

        Args:
            channel_id: The ID of the channel containing the message.
            message_ts: The timestamp of the message.
            reaction: The name of the reaction to add.
        '''
        self.client.reactions_add(
            channel=channel_id,
            timestamp=message_ts,
            name=reaction,
        )

    def remove_bot_reactions(self, channel_id: str, message_ts: str) -> None:
        '''
        Remove multiple reactions from a Slack message.

        Args:
            channel_id: The ID of the channel containing the message.
            message_ts: The timestamp of the message.
        '''
        reactions: list[dict] = (
            self.client.reactions_get(
                channel=channel_id,
                timestamp=message_ts,
            )
            .get('message', {})
            .get('reactions', [])  # type: ignore[call-overload]
        )

        if not reactions:
            return

        for reaction in reactions:
            if self.bot_id not in reaction.get('users', []):
                continue

            reaction_name = reaction.get('name')

            if not reaction_name:
                continue

            self.client.reactions_remove(
                channel=channel_id,
                timestamp=message_ts,
                name=reaction_name,
            )
