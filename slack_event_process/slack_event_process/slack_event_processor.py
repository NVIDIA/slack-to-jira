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
Slack event processor module for handling Slack events and Jira integration.

This module provides functionality to process Slack events, manage Jira issue
registrations, and handle comment synchronization between Slack and Jira.
'''

from __future__ import annotations

import logging
from typing import Optional

import event

logger = logging.getLogger()


class SlackEventProcessor:  # pylint: disable=too-few-public-methods
    '''
    A processor for handling Slack events and managing Jira integration.

    This class processes Slack events, manages Jira issue registrations,
    and handles comment synchronization between Slack and Jira systems.
    '''

    def __init__(
        self,
        event_factory: Optional[event.EventFactory] = None,
    ) -> None:
        self.event_factory = event_factory

    def _create_event(self, event_dict: dict) -> event.Event:
        if self.event_factory is None:
            raise ValueError('Event factory is not set')

        return self.event_factory.create_event(event_dict)

    def _process(self, event_obj: event.Event) -> None:
        event_obj.handle_event()

    def process(self, event_dict: dict) -> None:
        '''
        Process a Slack event and handle the appropriate action.

        Args:
            event_dict: The Slack event dictionary to process.
        '''

        # Since the event is verified before reaching the processor,
        # this call should not raise, but return a valid event.
        # If it fails, there are two main possibilities:
        # 1. The event is not valid. The verifier is thus accepting invalid events.
        # 2. The event is valid, but the event factory is not able to create an event.
        # Since at this time we are not sure which case it is, we need to let the lambda call fail.
        try:
            event_obj = self._create_event(event_dict)
        except:  # pylint: disable=bare-except
            logger.error(f'Encountered exception while creating event: {event_dict}')
            raise

        self._process(event_obj)
