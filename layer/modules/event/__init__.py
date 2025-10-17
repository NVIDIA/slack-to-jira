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
Event handling package for Slack bot event processing.

This package provides a hierarchical event system for processing Slack events
using the template method and factory patterns. Events are dispatched based on
type and command, allowing extensible handling of different Slack interactions.

Event Hierarchy:
    Event (ABC)
    ├── AppMentionEvent
    │   ├── AppMentionRegisterEvent - Links threads to Jira issues
    │   └── AppMentionDeregisterEvent - Unlinks threads from Jira issues
    └── ReactionEvent
        └── ReactionSyncEvent - Syncs messages to Jira as comments

Usage:
    The event system is typically accessed through the EventFactory:

    >>> from event import EventFactory
    >>> factory = EventFactory(slack_wrapper, jira_wrapper, dynamo_wrapper)
    >>>
    >>> # Process an app mention event
    >>> event = factory.create_event({
    ...     'type': 'app_mention',
    ...     'text': '@bot register PROJ-123'
    ... })
    >>> event.handle_event()  # Processes and acknowledges
    >>>
    >>> # Process a reaction event
    >>> event = factory.create_event({
    ...     'type': 'reaction_added',
    ...     'reaction': 'speech_balloon'
    ... })
    >>> event.handle_event()  # Syncs message to Jira

Architecture:
    - Events self-register with the factory when imported
    - Template method pattern ensures consistent processing flow
    - Dependency injection provides access to external services
    - Abstract base class enforces implementation contracts

See Also:
    - event.Event: Base class with template method implementation
    - event_factory.EventFactory: Factory for creating event instances
'''

from .event import Event
from .app_mention_event import AppMentionEvent
from .app_mention_register_event import AppMentionRegisterEvent
from .app_mention_deregister_event import AppMentionDeregisterEvent
from .reaction_event import ReactionEvent
from .reaction_sync_event import ReactionSyncEvent

from .event_factory import EventFactory

__all__ = [
    'Event',
    'AppMentionEvent',
    'AppMentionRegisterEvent',
    'AppMentionDeregisterEvent',
    'ReactionEvent',
    'ReactionSyncEvent',
    'EventFactory',
]
