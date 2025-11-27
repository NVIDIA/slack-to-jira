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
Reaction event module for handling Slack reaction_added events.

This module provides the ReactionEvent class that processes events triggered
when users add emoji reactions to messages in Slack channels.
'''

from __future__ import annotations

import logging
from typing import Any

from .event import Event
from .event_factory import EventFactory

logger = logging.getLogger()


class ReactionEvent(Event):
    '''
    Event handler for Slack reaction_added events.

    This class processes events when users add emoji reactions to messages.
    It extracts the reaction type (emoji name) to determine which concrete
    event handler should process it (e.g., sync reaction for comment syncing).

    The class serves as an intermediate abstract class in the event hierarchy:
    Event -> ReactionEvent -> ReactionSyncEvent

    Unlike app_mention events which extract text, reaction events extract the
    emoji name and use the 'item' structure to get channel and message info.

    Attributes:
        name: The Slack event type name ('reaction_added').
        channel_id: The channel ID where the reaction was added.
        message_ts: The timestamp of the message that received the reaction.
    '''

    name: str = 'reaction_added'

    @classmethod
    def infer_subtype(cls, event_data: dict) -> tuple[str, Any]:
        '''
        Infer the reaction subtype from the emoji name.

        Extracts the emoji/reaction name from the event to determine which
        concrete event class should handle it. For example, a "speech_balloon"
        reaction triggers comment syncing to Jira.

        Args:
            event_data: The Slack event dictionary containing the 'reaction' field.

        Returns:
            A tuple of (reaction_name, None) where reaction_name is the emoji
            identifier (e.g., "speech_balloon", "thumbsup") and args is None
            since reactions don't have additional arguments.
        '''
        args = None
        logger.info(f'Infer subtype: {event_data}')
        return event_data.get('reaction'), args  # type: ignore

    def _handle_event_type(self, event_data: dict) -> None:
        '''
        Extract and validate reaction_added event data.

        Parses the Slack reaction_added event to extract required fields
        from the 'item' structure, which contains information about what
        was reacted to. Currently only supports message reactions.

        Args:
            event_data: The Slack event dictionary containing reaction data.
                       The 'item' field contains channel and timestamp.

        Sets:
            self.channel_id: The Slack channel ID where reaction occurred.
            self.message_ts: The timestamp of the reacted message.
        '''
        event_data = event_data.get('item', {})
        self.channel_id = event_data.get('channel')
        self.message_ts = event_data.get('ts')

    def construct_message_group_id(self) -> str:
        '''
        Construct a message group ID for reaction events.

        Creates a unique identifier by combining the channel ID and message
        timestamp. This is used for message deduplication and grouping related
        reactions to the same message.

        Returns:
            A string in the format 'channel_id_message_ts' that uniquely
            identifies the message that was reacted to.

        Example:
            'C1234567890_1234567890.123456'
        '''
        return '_'.join((self.channel_id, self.message_ts))  # type: ignore


# Register this event type with the factory for automatic routing
EventFactory.top_level_event_types[ReactionEvent.name] = (
    ReactionEvent  # type: ignore[type-abstract]
)
