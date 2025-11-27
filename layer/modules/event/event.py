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
Event module for handling Slack events with template method pattern.

This module provides the base Event class and metaclass for enforcing
architectural constraints on event handling.
'''

from __future__ import annotations

from abc import ABC, ABCMeta, abstractmethod
import inspect
import logging
from typing import Any, Callable, final, Optional, TYPE_CHECKING

from .config import CONFIG

from .exceptions import NotHandledException, IgnorableException

if TYPE_CHECKING:
    from jira_wrapper import JiraWrapper
    from slack_sdk_wrapper import SlackSdkWrapper
    from dynamodb_wrapper import DynamoDbWrapper

logger = logging.getLogger()


class NoInitOverride(ABCMeta):
    '''
    Metaclass that prevents subclasses from overriding __init__.

    This ensures that all Event subclasses use the base Event.__init__
    method, maintaining consistent initialization behavior and preventing
    accidental breaks in the template method pattern.
    '''

    def __init__(cls, name: str, bases: tuple[type], namespace: dict):
        '''
        Initialize the metaclass and enforce __init__ constraint.

        Args:
            name: The name of the class being created.
            bases: The base classes of the class being created.
            namespace: The namespace (attributes) of the class being created.

        Raises:
            TypeError: If a subclass (non-ABC) defines __init__.
        '''
        if '__init__' in namespace and any(base is not ABC for base in bases):
            raise TypeError(f'{cls.__name__} must not define __init__')

        super().__init__(name, bases, namespace)


class Event(ABC, metaclass=NoInitOverride):
    '''
    Abstract base class for all Slack events using template method pattern.

    This class provides a framework for processing Slack events with consistent
    error handling, acknowledgment, and lifecycle management. Subclasses must
    implement abstract methods to define event-specific behavior.

    The template method pattern ensures all events follow the same processing flow:
    1. Parse event type (_handle_event_type)
    2. Parse event subtype (_handle_event_sub_type)
    3. Validate required fields (message_ts, channel_id)
    4. Process the event (_process_event)
    5. Acknowledge success/failure with Slack reactions

    Attributes:
        success_reaction: Emoji name for successful event processing.
        error_reaction: Emoji name for failed event processing.
        jira_wrapper: Interface to Jira API operations.
        slack_sdk_wrapper: Interface to Slack API operations.
        dynamo_db_wrapper: Interface to DynamoDB operations.
        message_ts: Slack message timestamp (required).
        channel_id: Slack channel ID (required).
    '''

    success_reaction: str = CONFIG['success_reaction']
    error_reaction: str = CONFIG['error_reaction']

    message_ts: Optional[str] = None
    channel_id: Optional[str] = None
    # pylint: disable=undefined-variable
    jira_wrapper: Optional[JiraWrapper]
    slack_sdk_wrapper: SlackSdkWrapper
    dynamo_db_wrapper: Optional[DynamoDbWrapper]

    @final
    def __init__(
        self,
        event_data: dict,
        args: Any,
        jira_wrapper: Optional[JiraWrapper],
        slack_sdk_wrapper: SlackSdkWrapper,
        dynamo_db_wrapper: Optional[DynamoDbWrapper],
    ) -> None:
        '''
        Initialize an event with dependencies and validate structure.

        This method is final and cannot be overridden by subclasses. It implements
        the template method pattern by calling hook methods that subclasses must
        implement, then validates that required fields were set.

        Args:
            event_data: The raw Slack event dictionary.
            args: Parsed arguments specific to the event subtype.
            jira_wrapper: Wrapper for Jira API operations.
            slack_sdk_wrapper: Wrapper for Slack API operations.
            dynamo_db_wrapper: Wrapper for DynamoDB operations.

        Raises:
            NotHandledException: If message_ts or channel_id are not set by subclasses.
        '''
        self.jira_wrapper = jira_wrapper
        self.slack_sdk_wrapper = slack_sdk_wrapper
        self.dynamo_db_wrapper = dynamo_db_wrapper

        self.message_ts = None
        self.channel_id = None

        self._handle_event_type(event_data)
        self._handle_event_sub_type(args)

        if self.message_ts is None or self.channel_id is None:
            raise NotHandledException(
                'Message timestamp and channel ID are required',
            )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        '''
        Hook for subclass initialization to handle abstract method overriding.

        This method nullifies infer_subtype for concrete leaf classes that don't
        need their own implementation, allowing intermediate abstract classes to
        provide implementations while preventing concrete classes from being required
        to implement it.

        Args:
            **kwargs: Keyword arguments passed to __init_subclass__.
        '''
        super().__init_subclass__(**kwargs)
        if inspect.isabstract(cls):
            return

        if 'infer_subtype' in cls.__dict__:
            cls.infer_subtype = None  # type: ignore

    @classmethod
    @abstractmethod
    def infer_subtype(cls, event_data: dict) -> tuple[str, Any]:
        '''
        Infer the concrete event subtype from event data.

        This class method examines the event data to determine which concrete
        event class should handle it and extracts relevant arguments for processing.

        Args:
            event_data: The raw Slack event dictionary.

        Returns:
            A tuple of (subtype_name, args) where subtype_name is a string
            identifying the concrete event type and args are parsed arguments
            for that event type.
        '''

    @abstractmethod
    def _handle_event_type(self, event_data: dict) -> None:
        '''
        Parse and extract top-level event type data.

        Subclasses must implement this to extract required fields (channel_id,
        message_ts, etc.) from the event data and store them as instance attributes.

        Args:
            event_data: The raw Slack event dictionary.

        Raises:
            NotHandledException: If required fields are missing from event data.
        '''

    @abstractmethod
    def _handle_event_sub_type(self, args: Any) -> None:
        '''
        Parse and extract event subtype-specific data.

        Subclasses must implement this to extract and validate subtype-specific
        arguments and store them as instance attributes for use in _process_event.

        Args:
            args: Parsed arguments specific to this event subtype.

        Raises:
            IgnorableException: If the event is invalid but should not be retried.
        '''

    @final
    def handle_event(self) -> None:
        '''
        Process the event with consistent error handling and acknowledgment.

        This is the main template method that orchestrates event processing:
        1. Calls _process_event() to do the actual work
        2. Catches and categorizes exceptions
        3. Acknowledges success or failure with Slack reactions
        4. Re-raises non-ignorable exceptions for Lambda retry

        The method is final to ensure all events follow the same processing flow.

        Raises:
            Exception: Re-raises non-IgnorableException errors for Lambda retry.
        '''
        try:
            self._process_event()
        except NotHandledException:
            self.acknowledge_event_not_handled()
        except Exception as e:
            logger.error(f'Encountered exception while executing operation: {e}')
            self.acknowledge_event_error()

            if not isinstance(e, IgnorableException):
                raise
        else:
            self.acknowledge_event_success()

    @abstractmethod
    def _process_event(self) -> None:
        '''
        Execute the event-specific business logic.

        Subclasses must implement this method to perform the actual work of
        processing the event (e.g., registering threads, adding comments, etc.).

        Raises:
            IgnorableException: For errors that should not trigger retry.
            NotHandledException: For events that cannot be processed.
            Exception: For errors that should trigger Lambda retry.
        '''

    @staticmethod
    def _acknowledge_prepare(func: Callable) -> Callable:
        '''
        Prepare the event for acknowledgement.
        '''

        def wrapper(self: Event) -> None:
            try:
                self.slack_sdk_wrapper.remove_bot_reactions(self.channel_id, self.message_ts)  # type: ignore # pylint: disable=line-too-long
                func(self)
            except self.slack_sdk_wrapper.ClientException:
                logger.error(
                    f'Failed to handle bot reactions for {func.__name__}: {self.channel_id}'
                    f', {self.message_ts}'
                )

        return wrapper

    @_acknowledge_prepare
    def acknowledge_event_success(self) -> None:
        '''
        Acknowledge successful event processing with a Slack reaction.

        Adds a success reaction emoji (e.g., checkmark) to the message that
        triggered the event, providing visual feedback to users.
        '''
        logger.info(
            f'Acknowledging event success: {self.channel_id}, {self.message_ts}, '
            f'{self.success_reaction}'
        )
        self.slack_sdk_wrapper.add_reaction(
            self.channel_id,  # type: ignore
            self.message_ts,  # type: ignore
            self.success_reaction,
        )

    @_acknowledge_prepare
    def acknowledge_event_error(self) -> None:
        '''
        Acknowledge failed event processing with a Slack reaction.

        Adds an error reaction emoji (e.g., X mark) to the message that
        triggered the event, indicating to users that processing failed.
        '''
        logger.info(
            f'Acknowledging event error: {self.channel_id}, {self.message_ts}, '
            f'{self.error_reaction}'
        )
        self.slack_sdk_wrapper.add_reaction(self.channel_id, self.message_ts, self.error_reaction)  # type: ignore # pylint: disable=line-too-long

    @_acknowledge_prepare
    def acknowledge_event_not_handled(self) -> None:
        '''
        Acknowledge that an event was not handled.

        Currently logs the event but does not add a reaction. This is for events
        that are structurally valid but cannot be processed (e.g., missing data).
        '''
        logger.info(f'Acknowledging event not handled: {self.channel_id}, {self.message_ts}')

    @staticmethod
    def _get_thread_id(thread_ts: str, channel: str) -> str:
        '''
        Generate a unique thread ID from thread timestamp and channel.

        Args:
            thread_ts: The thread timestamp.
            channel: The channel ID.

        Returns:
            A unique thread identifier.
        '''
        return f'{channel}_{thread_ts}'

    @abstractmethod
    def construct_message_group_id(self) -> str:
        '''
        Construct a message group ID based on the event type.
        '''
