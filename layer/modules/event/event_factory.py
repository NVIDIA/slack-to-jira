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
Event factory module for creating event objects from Slack event data.

This module provides the EventFactory class that uses the factory pattern
to instantiate appropriate event handler classes based on Slack event types
and commands.
'''

from __future__ import annotations

import copy
import logging

from typing import TYPE_CHECKING, Dict, Type, Optional

if TYPE_CHECKING:
    from event import Event
    from slack_sdk_wrapper import SlackSdkWrapper
    from jira_wrapper import JiraWrapper
    from dynamodb_wrapper import DynamoDbWrapper

logger = logging.getLogger()


class EventFactory:  # pylint: disable=too-few-public-methods
    '''
    Factory for creating event objects from Slack event data.

    This class implements a two-stage factory pattern:
    1. Top-level event types (app_mention, reaction_added) - registered by intermediate classes
    2. Concrete event types (register, deregister, sync) - registered by leaf classes

    Event classes self-register by adding themselves to the class-level dictionaries
    when their modules are imported. This provides a plugin-like architecture where
    new event types can be added without modifying the factory itself.

    The factory creates event objects with dependency injection, passing in
    wrappers for Slack, Jira, and DynamoDB operations.

    Attributes:
        top_level_event_types: Dict mapping Slack event types to intermediate event classes.
        concrete_event_types: Dict mapping command names to concrete event handler classes.
        slack_sdk_wrapper: Wrapper for Slack API operations.
        jira_wrapper: Wrapper for Jira API operations.
        dynamo_db_wrapper: Wrapper for DynamoDB operations.

    Example:
        factory = EventFactory(slack_wrapper, jira_wrapper, dynamo_wrapper)
        event = factory.create_event({'type': 'app_mention', 'text': '@bot register PROJ-123'})
        # Returns AppMentionRegisterEvent instance
    '''

    class UndefinedCommand(Exception):
        '''
        Exception raised when an unknown event type or command is encountered.

        This exception is raised during event creation when:
        - The top-level event type is not recognized (e.g., unknown Slack event)
        - The concrete command type is not recognized (e.g., unknown bot command)
        '''

    top_level_event_types: Dict[str, Type[Event]] = {}
    concrete_event_types: Dict[str, Type[Event]] = {}

    def __init__(
        self,
        slack_sdk_wrapper: SlackSdkWrapper,
        jira_wrapper: Optional[JiraWrapper],
        dynamo_db_wrapper: Optional[DynamoDbWrapper],
    ) -> None:
        '''
        Initialize the factory with service wrappers.

        The wrappers are stored and later injected into created event objects,
        providing them with access to external services (Slack, Jira, DynamoDB).

        Args:
            slack_sdk_wrapper: Wrapper for Slack API operations.
            jira_wrapper: Wrapper for Jira API operations (can be None for validation).
            dynamo_db_wrapper: Wrapper for DynamoDB operations (can be None for validation).
        '''
        self.slack_sdk_wrapper = slack_sdk_wrapper
        self.jira_wrapper = jira_wrapper
        self.dynamo_db_wrapper = dynamo_db_wrapper

    def create_event(self, event_data: dict) -> Event:
        '''
        Create an appropriate event object from Slack event data.

        This method implements a two-stage dispatch process:
        1. Identifies top-level event type from 'type' field (e.g., 'app_mention')
        2. Calls infer_subtype() on that class to determine concrete type (e.g., 'register')
        3. Instantiates the concrete event class with injected dependencies

        The event_data is deep-copied to prevent mutations from affecting the original.
        The 'type' field is removed after reading to avoid passing it to event constructors.

        Args:
            event_data: Slack event dictionary containing at minimum a 'type' field.
                       Expected format matches Slack's Event API structure.

        Returns:
            An instance of a concrete Event subclass (e.g., AppMentionRegisterEvent).

        Raises:
            UndefinedCommand: If the event type or command is not registered.

        Example:
            >>> factory.create_event({'type': 'app_mention', 'text': '@bot register PROJ-123'})
            <AppMentionRegisterEvent object>

            >>> factory.create_event({'type': 'reaction_added', 'reaction': 'speech_balloon'})
            <ReactionSyncEvent object>
        '''
        logger.info(self.top_level_event_types, self.concrete_event_types)
        event_data = copy.deepcopy(event_data)
        event_type = event_data.pop('type', None)
        if not event_type or event_type not in self.top_level_event_types:
            raise self.UndefinedCommand(f'Unknown top level event type: {event_type}')

        sub_event_type, args = self.top_level_event_types[event_type].infer_subtype(event_data)

        if not sub_event_type or sub_event_type not in self.concrete_event_types:
            raise self.UndefinedCommand(f'Unknown concrete event type: {sub_event_type}')

        return self.concrete_event_types[sub_event_type](
            event_data,
            args,
            slack_sdk_wrapper=self.slack_sdk_wrapper,
            jira_wrapper=self.jira_wrapper,
            dynamo_db_wrapper=self.dynamo_db_wrapper,
        )
