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
Custom exceptions for event handling in the Slack bot.

This module defines exception types used to control event processing flow
and Lambda retry behavior. These exceptions enable fine-grained control over
error handling and acknowledgment strategies.
'''


class NotHandledException(Exception):
    '''
    Exception raised when an event cannot be handled due to missing data.

    This exception is used for events that are structurally valid but lack
    required information to be processed. For example:
    - App mention event missing thread_ts
    - App mention event missing channel ID
    - Event with incomplete or missing fields

    When this exception is raised:
    - The event is acknowledged as "not handled" (logged, no reaction added)
    - The Lambda execution completes successfully (no retry)
    - The event is effectively discarded

    This is appropriate for events that will never become valid, preventing
    infinite retry loops for malformed events.

    Example:
        >>> if not event_data.get('thread_ts'):
        ...     raise NotHandledException('Missing thread_ts in app mention event')
    '''


class IgnorableException(Exception):
    '''
    Exception raised for errors that should not trigger Lambda retry.

    This exception is used for business logic failures that are expected
    and should not result in retrying the event. For example:
    - Invalid command format (user error)
    - Attempting to deregister a non-existent link
    - Syncing comment to a thread with no registered Jira issues

    When this exception is raised:
    - The event is acknowledged with an error reaction (❌)
    - The Lambda execution completes successfully (no retry)
    - The error is logged for visibility

    This prevents retrying events that will always fail due to business
    rules or user input errors, while still providing feedback to users.

    Use this for:
    - User input validation failures
    - Expected business rule violations
    - Recoverable errors that don't need retry

    Do NOT use for:
    - Network errors (let Lambda retry)
    - Transient API failures (let Lambda retry)
    - Unexpected system errors (let Lambda retry)

    Example:
        >>> if not registration_exists:
        ...     raise IgnorableException('Jira issue not registered to this thread')
    '''
