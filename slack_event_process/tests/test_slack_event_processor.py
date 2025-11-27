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

# pylint: disable=too-many-locals, missing-class-docstring, import-outside-toplevel, missing-function-docstring, unused-argument, missing-module-docstring, too-many-arguments, protected-access, too-many-lines
# mypy: disable-error-code=no-untyped-def

from abc import ABC
from contextlib import ExitStack
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import json
import os
from typing import Dict, Any, Optional, Tuple, List, Callable
from unittest.mock import Mock, patch
from urllib.error import URLError

import aiohttp
import boto3
from atlassian import Jira
from moto import mock_aws
import pytest
import requests
from slack_sdk.http_retry.builtin_handlers import (
    ConnectionErrorRetryHandler,
    RateLimitErrorRetryHandler,
)
from slack_sdk.web.client import WebClient

from slack_sdk_wrapper import SlackSdkWrapper
from jira_wrapper import JiraWrapper
from dynamodb_wrapper import DynamoDbWrapper

os.environ['SUCCESS_REACTION'] = 'tick'
os.environ['ERROR_REACTION'] = 'x'
os.environ['ICON_URL'] = 'https://example.com/icon.png'
os.environ['ICON_TITLE'] = 'Test Icon'
os.environ['SYNC_REACTION'] = 'sync'
os.environ['APP_NAME'] = 'app-name'

# pylint:disable=wrong-import-position
import event  # pylint:disable=unused-import
from event.event_factory import EventFactory
from event.exceptions import NotHandledException
from event.config import CONFIG
from event.reaction_sync_event import AsyncSlackToJiraTransfer

from slack_event_process.slack_event_processor import SlackEventProcessor


DYNAMODB_TABLE_NAME = 'test-slack-jira-table'
JIRA_SERVER_URL = 'https://test-jira.atlassian.net'
JIRA_TOKEN = 'test_jira_token'
ICON_URL = 'https://example.com/icon.png'
ICON_TITLE = 'Test Icon'
SLACK_SERVER_URL = 'https://test.slack.com'


@pytest.fixture()
def aws_setup():
    with mock_aws():
        os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
        yield


@pytest.fixture()
def dynamodb_table(aws_setup):
    '''
    Create a DynamoDB table for testing.
    '''
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    table = dynamodb.create_table(
        TableName=DYNAMODB_TABLE_NAME,
        KeySchema=[
            {'AttributeName': 'slack_thread_id', 'KeyType': 'HASH'},
            {'AttributeName': 'jira_issue_id', 'KeyType': 'RANGE'},
        ],
        AttributeDefinitions=[
            {'AttributeName': 'jira_issue_id', 'AttributeType': 'S'},
            {'AttributeName': 'slack_thread_id', 'AttributeType': 'S'},
        ],
        BillingMode='PAY_PER_REQUEST',
    )
    return table


@pytest.fixture
def dynamodb_wrapper(dynamodb_table):
    return DynamoDbWrapper(DYNAMODB_TABLE_NAME)


@pytest.fixture
def event_factory(dynamodb_wrapper):
    slack_sdk_wrapper = SlackSdkWrapper()
    jira_wrapper = JiraWrapper()

    slack_sdk_wrapper.client = Mock(spec=WebClient)
    slack_sdk_wrapper.client.token = 'test_slack_token'

    jira_wrapper.jira = Mock(spec=Jira)
    jira_wrapper.jira_token = 'test_jira_token'
    jira_wrapper.server_url = 'https://test-jira.atlassian.net'

    return EventFactory(slack_sdk_wrapper, jira_wrapper, dynamodb_wrapper)


@pytest.fixture
def processor(event_factory):
    '''
    Fixture for SlackEventProcessor with mocked dependencies.
    '''
    return SlackEventProcessor(
        event_factory=event_factory,
    )


class EventType(Enum):
    APP_MENTION = 'app_mention'
    REACTION_ADDED = 'reaction_added'


@dataclass
class MockEvent(ABC):
    event_type: EventType = field(init=False)
    event_dict: Dict[str, Any] = field(init=False, default_factory=dict)


@dataclass
class MockAppMentionEvent(MockEvent):
    instance = event.AppMentionEvent
    ts: Optional[str] = None
    thread_ts: Optional[str] = None
    channel: Optional[str] = None
    text: Optional[str] = None

    def __post_init__(self):
        self.event_type = EventType.APP_MENTION
        self.event_dict = {
            'ts': self.ts,
            'thread_ts': self.thread_ts,
            'channel': self.channel,
            'text': self.text,
            'type': self.event_type.value,
        }
        self.event_dict = {k: v for k, v in self.event_dict.items() if v is not None}


@dataclass
class MockAppMentionRegisterEvent(MockAppMentionEvent):
    instance = event.AppMentionRegisterEvent
    user_id: str = 'U1234567890'
    jira_issue_id: str = 'PROJ-123'
    link_text: str = ''

    def __post_init__(self):
        self.text = f'<@U{self.user_id}> register {self.jira_issue_id} {self.link_text}'
        super().__post_init__()


@dataclass
class MockAppMentionDeregisterEvent(MockAppMentionEvent):
    instance = event.AppMentionDeregisterEvent
    user_id: str = 'U1234567890'

    def __post_init__(self):
        self.text = f'<@U{self.user_id}> deregister {self.text}'
        super().__post_init__()


@dataclass
class MockReactionAddedEvent(MockEvent):
    instance = event.ReactionSyncEvent
    reaction: Optional[str] = None
    channel: Optional[str] = None
    ts: Optional[str] = None

    def __post_init__(self):
        self.event_type = EventType.REACTION_ADDED
        self.event_dict = {
            'reaction': self.reaction,
            'item': {'channel': self.channel, 'ts': self.ts},
            'type': self.event_type.value,
        }

        self.event_dict['item'] = {
            k: v for k, v in self.event_dict['item'].items() if v is not None
        }


@dataclass
class Scenario(ABC):
    name: str

    def __init__(self, name: str):
        self.name = name

    def __str__(self):
        return self.name


@dataclass
class MockHighLevelProcessEventScenario(Scenario):
    event_obj: MockAppMentionEvent | MockReactionAddedEvent


HIGH_LEVEL_PROCESS_EVENT_SCENARIOS = [
    MockHighLevelProcessEventScenario(
        name='app_mention_success',
        event_obj=MockAppMentionRegisterEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            text='PROJ-123',
        ),
    ),
    MockHighLevelProcessEventScenario(
        name='reaction_added_success',
        event_obj=MockReactionAddedEvent(
            reaction=CONFIG['sync_reaction'],
            channel='C1234567890',
            ts='1234567890.123456',
        ),
    ),
    MockHighLevelProcessEventScenario(
        name='app_mention_error',
        event_obj=MockAppMentionRegisterEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            text='PROJ-123',
        ),
    ),
    MockHighLevelProcessEventScenario(
        name='app_mention_ignorable_error',
        event_obj=MockAppMentionDeregisterEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            text='PROJ-123',
        ),
    ),
]


@pytest.mark.parametrize('test_case', HIGH_LEVEL_PROCESS_EVENT_SCENARIOS, ids=str)
def test_process_events_basic(processor, test_case: MockHighLevelProcessEventScenario):
    event_dict = test_case.event_obj.event_dict
    event_obj = processor.event_factory.create_event(event_dict)
    with ExitStack() as stack:
        stack.enter_context(patch.object(event_obj.slack_sdk_wrapper, 'remove_bot_reactions'))

        mock_process = stack.enter_context(patch.object(event_obj, '_process_event'))

        processor._process(event_obj)
        mock_process.assert_called_once()


@dataclass
class AppMentionCommandScenario(Scenario):
    event_obj: MockEvent
    expected_method: str
    expected_args: Tuple[Any, ...]
    expected_kwargs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AppMentionValidationScenario(Scenario):
    event_obj: MockEvent
    expected_exception: Optional[type] = None


APP_MENTION_VALIDATION_SCENARIOS = [
    AppMentionValidationScenario(
        name='missing_thread_ts',
        event_obj=MockAppMentionEvent(
            ts='9876543210.987654',
            channel='C1234567890',
            text='<@U1234567890> register PROJ-123',
        ),
        expected_exception=NotHandledException,
    ),
    AppMentionValidationScenario(
        name='missing_channel',
        event_obj=MockAppMentionEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            text='<@U1234567890> register PROJ-123',
        ),
        expected_exception=NotHandledException,
    ),
    AppMentionValidationScenario(
        name='missing_text',
        event_obj=MockAppMentionEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
        ),
        expected_exception=EventFactory.UndefinedCommand,
    ),
    AppMentionValidationScenario(
        name='empty_text',
        event_obj=MockAppMentionEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            text='<@U1234567890>',
        ),
        expected_exception=EventFactory.UndefinedCommand,
    ),
    AppMentionValidationScenario(
        name='invalid_command_format',
        event_obj=MockAppMentionEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            text='<@U1234567890> invalid',
        ),
        expected_exception=EventFactory.UndefinedCommand,
    ),
    AppMentionValidationScenario(
        name='invalid_command',
        event_obj=MockAppMentionEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            text='<@U1234567890> invalid PROJ-123',
        ),
        expected_exception=EventFactory.UndefinedCommand,
    ),
]


@pytest.mark.parametrize('test_case', APP_MENTION_VALIDATION_SCENARIOS, ids=str)
def test_process_app_mention_validation(event_factory, test_case: AppMentionValidationScenario):
    event_dict = test_case.event_obj.event_dict

    if test_case.expected_exception:
        with pytest.raises(test_case.expected_exception):
            event_factory.create_event(event_dict)
    else:
        event_factory.create_event(event_dict)


@dataclass
class JiraRegistrationScenario(Scenario):
    event_obj: MockEvent

    existing_dynamodb_event: Optional[dict]
    expected_dynamodb_event: Optional[dict]
    existing_remote_link: Optional[dict]
    expected_jira_call: str


JIRA_REGISTRATION_SCENARIOS = [
    JiraRegistrationScenario(
        name='new_registration',
        event_obj=MockAppMentionEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            text='<@U1234567890> register PROJ-123',
        ),
        existing_dynamodb_event=None,
        expected_dynamodb_event={
            'jira_issue_id': 'PROJ-123',
            'slack_thread_id': 'C1234567890_1234567890.123457',
        },
        existing_remote_link=None,
        expected_jira_call='add_link',
    ),
    JiraRegistrationScenario(
        name='register_new_with_custom_link_text',
        event_obj=MockAppMentionEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            text='<@U1234567890> register PROJ-123 Custom Link Text',
        ),
        existing_dynamodb_event=None,
        expected_dynamodb_event={
            'jira_issue_id': 'PROJ-123',
            'slack_thread_id': 'C1234567890_1234567890.123457',
        },
        existing_remote_link=None,
        expected_jira_call='add_link',
    ),
    JiraRegistrationScenario(
        name='register_existing_valid_link',
        event_obj=MockAppMentionEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            text='<@U1234567890> register PROJ-123 New custom Link Text',
        ),
        existing_dynamodb_event={
            'jira_issue_id': 'PROJ-123',
            'slack_thread_id': 'C1234567890_1234567890.123457',
            'jira_link_id': '1234567890',
        },
        expected_dynamodb_event={
            'jira_issue_id': 'PROJ-123',
            'slack_thread_id': 'C1234567890_1234567890.123457',
        },
        existing_remote_link={'id': '1234567890'},
        expected_jira_call='update_link',
    ),
    JiraRegistrationScenario(
        name='register_existing_invalid_link',
        event_obj=MockAppMentionEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            text='<@U1234567890> register PROJ-123',
        ),
        existing_dynamodb_event={
            'jira_issue_id': 'PROJ-123',
            'slack_thread_id': 'C1234567890_1234567890.123457',
        },
        expected_dynamodb_event={
            'jira_issue_id': 'PROJ-123',
            'slack_thread_id': 'C1234567890_1234567890.123457',
        },
        existing_remote_link=None,
        expected_jira_call='add_link',
    ),
    JiraRegistrationScenario(
        name='deregister_existing_valid_link',
        event_obj=MockAppMentionEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            text='<@U1234567890> deregister PROJ-123',
        ),
        existing_dynamodb_event={
            'jira_issue_id': 'PROJ-123',
            'slack_thread_id': 'C1234567890_1234567890.123457',
            'jira_link_id': '1234567890',
        },
        existing_remote_link={'id': '1234567890'},
        expected_dynamodb_event=None,
        expected_jira_call='remove_link',
    ),
]


@pytest.mark.parametrize('test_case', JIRA_REGISTRATION_SCENARIOS, ids=str)
def test_register_jira_issue_scenarios(processor, test_case: JiraRegistrationScenario):
    event_dict = test_case.event_obj.event_dict
    existing_dynamodb_event = test_case.existing_dynamodb_event
    expected_dynamodb_event = test_case.expected_dynamodb_event
    expected_jira_call = test_case.expected_jira_call

    if existing_dynamodb_event:
        processor.event_factory.dynamo_db_wrapper.put_item(existing_dynamodb_event)

    with ExitStack() as stack:
        mock_jira_call = stack.enter_context(
            patch.object(processor.event_factory.jira_wrapper, expected_jira_call)
        )
        stack.enter_context(
            patch.object(
                processor.event_factory.jira_wrapper,
                'validate_link',
                return_value=True,
            )
        )
        stack.enter_context(
            patch.multiple(
                processor.event_factory.slack_sdk_wrapper,
                get_channel_name=Mock(return_value='test-channel'),
                get_message_link=Mock(
                    return_value='https://test.slack.com/messages/test-channel/1234567890.123456'
                ),
                remove_bot_reactions=Mock(),
            )
        )

        processor.process(event_dict)
        mock_jira_call.assert_called()

    if expected_dynamodb_event:
        dynamodb_key = {
            'jira_issue_id': expected_dynamodb_event['jira_issue_id'],
            'slack_thread_id': expected_dynamodb_event['slack_thread_id'],
        }
        item = processor.event_factory.dynamo_db_wrapper.get_item(dynamodb_key)
        item.pop('created_at')
        item.pop('jira_link_id')
        assert item == expected_dynamodb_event
    elif existing_dynamodb_event:
        dynamodb_key = {
            'jira_issue_id': existing_dynamodb_event['jira_issue_id'],
            'slack_thread_id': existing_dynamodb_event['slack_thread_id'],
        }
        assert not processor.event_factory.dynamo_db_wrapper.get_item(dynamodb_key)


@dataclass
class JiraWrapperValidationScenario(Scenario):
    args: Tuple[Any, ...]
    jira_wrapper_call: str
    expected_jira_call: str
    expected_args: Tuple[Any, ...] = field(default_factory=tuple)
    expected_kwargs: Dict[str, Any] = field(default_factory=dict)


JIRA_WRAPPER_VALIDATION_SCENARIOS = [
    JiraWrapperValidationScenario(
        name='add_link',
        args=(
            'PROJ-123',
            'https://test.slack.com/messages/test-channel/1234567890.123456',
            'Titleeee',
            'https://example.com/icon.png',
            'Test Icon',
        ),
        jira_wrapper_call='add_link',
        expected_jira_call='create_or_update_issue_remote_links',
        expected_args=(
            'PROJ-123',
            'https://test.slack.com/messages/test-channel/1234567890.123456',
            'Titleeee',
        ),
        expected_kwargs={
            'icon_url': 'https://example.com/icon.png',
            'icon_title': 'Test Icon',
        },
    ),
    JiraWrapperValidationScenario(
        name='update_link',
        args=(
            'PROJ-123',
            '1234567890',
            'https://test.slack.com/messages/test-channel/1234567890.123456',
            'Titleeee',
        ),
        jira_wrapper_call='update_link',
        expected_jira_call='update_issue_remote_link_by_id',
        expected_args=(
            'PROJ-123',
            '1234567890',
            'https://test.slack.com/messages/test-channel/1234567890.123456',
            'Titleeee',
        ),
    ),
    JiraWrapperValidationScenario(
        name='remove_link',
        args=('PROJ-123', '1234567890'),
        jira_wrapper_call='remove_link',
        expected_jira_call='delete_issue_remote_link_by_id',
        expected_args=('PROJ-123', '1234567890'),
    ),
    JiraWrapperValidationScenario(
        name='add_comment',
        args=('PROJ-123', 'Test Comment'),
        jira_wrapper_call='add_comment',
        expected_jira_call='issue_add_comment',
        expected_args=('PROJ-123', 'Test Comment'),
    ),
    JiraWrapperValidationScenario(
        name='validate_link',
        args=('PROJ-123', '1234567890'),
        jira_wrapper_call='validate_link',
        expected_jira_call='get_issue_remote_link_by_id',
        expected_args=('PROJ-123', '1234567890'),
    ),
]


@pytest.mark.parametrize('test_case', JIRA_WRAPPER_VALIDATION_SCENARIOS, ids=str)
def test_jira_wrapper_validation(processor, test_case: JiraWrapperValidationScenario):
    args = test_case.args
    jira_wrapper_call = test_case.jira_wrapper_call
    expected_jira_call = test_case.expected_jira_call
    expected_args = test_case.expected_args
    expected_kwargs = test_case.expected_kwargs

    with patch.object(
        processor.event_factory.jira_wrapper.jira, expected_jira_call
    ) as mock_jira_call:
        getattr(processor.event_factory.jira_wrapper, jira_wrapper_call)(*args)
        mock_jira_call.assert_called_once_with(*expected_args, **expected_kwargs)


@dataclass
class ReactionAddedScenario(Scenario):
    event_obj: MockReactionAddedEvent
    existing_dynamodb_events: List[dict] = field(default_factory=list)

    channel_name: Optional[str] = field(default=None)
    add_comment: bool = field(default=True)
    expected_comment_count: Optional[int] = field(default=None)
    expected_reaction: Optional[str] = field(default=None)


REACTION_ADDED_SCENARIOS = [
    ReactionAddedScenario(
        name='registered_thread_gothic_sync_success',
        event_obj=MockReactionAddedEvent(
            reaction=CONFIG['sync_reaction'],
            channel='C1234567890',
            ts='1234567890.123456',
        ),
        channel_name='test-channel',
        existing_dynamodb_events=[
            {
                'jira_issue_id': 'PROJ-123',
                'slack_thread_id': 'C1234567890_1234567890.123456',
                'jira_link_id': '1234567890',
            }
        ],
        expected_reaction=CONFIG['success_reaction'],
    ),
    ReactionAddedScenario(
        name='unregistered_thread_gothic_sync_error',
        event_obj=MockReactionAddedEvent(
            reaction=CONFIG['sync_reaction'],
            channel='C9876543210',
            ts='9876543210.987654',
        ),
        expected_reaction=CONFIG['error_reaction'],
    ),
    ReactionAddedScenario(
        name='unrelated_reaction_no_action',
        event_obj=MockReactionAddedEvent(
            reaction='unrelated_reaction',
            channel='C1234567890',
            ts='1234567890.123456',
        ),
        existing_dynamodb_events=[
            {
                'jira_issue_id': 'PROJ-123',
                'slack_thread_id': 'C1234567890_1234567890.123456',
                'jira_link_id': '1234567890',
            }
        ],
        expected_reaction=None,
        expected_comment_count=0,
    ),
    ReactionAddedScenario(
        name='multiple_registered_issues_success',
        event_obj=MockReactionAddedEvent(
            reaction=CONFIG['sync_reaction'],
            channel='C5555555555',
            ts='5555555555.555555',
        ),
        channel_name='test-channel',
        existing_dynamodb_events=[
            {
                'jira_issue_id': 'PROJ-456',
                'slack_thread_id': 'C5555555555_1234567890.123456',
                'jira_link_id': '4567890123',
            },
            {
                'jira_issue_id': 'PROJ-789',
                'slack_thread_id': 'C5555555555_1234567890.123456',
                'jira_link_id': '7890123456',
            },
        ],
        expected_reaction=CONFIG['success_reaction'],
    ),
]


@pytest.mark.parametrize('test_case', REACTION_ADDED_SCENARIOS, ids=str)
def test_process_reaction_added(processor, test_case: ReactionAddedScenario):
    event_dict = test_case.event_obj.event_dict

    dynamo_db_wrapper = processor.event_factory.dynamo_db_wrapper
    expected_comment_count = (
        test_case.expected_comment_count
        if test_case.expected_comment_count is not None
        else len(test_case.existing_dynamodb_events)
    )

    for existing_dynamodb_event in test_case.existing_dynamodb_events:
        dynamo_db_wrapper.put_item(existing_dynamodb_event)

    comment_text = 'MESSAGEEEEEEEEE'
    with ExitStack() as stack:
        reaction_added_mock = stack.enter_context(
            patch.object(processor.event_factory.slack_sdk_wrapper, 'add_reaction')
        )
        comment_added_mock = stack.enter_context(
            patch.object(processor.event_factory.jira_wrapper, 'add_comment')
        )

        stack.enter_context(
            patch.multiple(
                processor.event_factory.slack_sdk_wrapper,
                get_content_from_message_ts=Mock(return_value=(comment_text, [])),
                get_thread_ts_from_message_ts=Mock(return_value='1234567890.123456'),
                get_message_link=Mock(
                    return_value='https://test.slack.com/messages/test-channel/1234567890.123456'
                ),
                remove_bot_reactions=Mock(),
            )
        )

        try:
            processor.process(event_dict)
        except:  # pylint: disable=bare-except
            pass

        assert comment_added_mock.call_count == expected_comment_count

        if test_case.expected_reaction:
            reaction_added_mock.assert_called_once()
            assert reaction_added_mock.call_args[0][2] == test_case.expected_reaction
        else:
            reaction_added_mock.assert_not_called()


@dataclass
class UtilityMethodScenario(Scenario):
    method: str
    class_: type
    args: Tuple[Any, ...]
    expected_result: Any


UTILITY_METHOD_SCENARIOS = [
    UtilityMethodScenario(
        name='get_thread_id',
        method='_get_thread_id',
        class_=event.ReactionSyncEvent,
        args=('1234567890.123457', 'C1234567890'),
        expected_result='C1234567890_1234567890.123457',
    ),
    UtilityMethodScenario(
        name='sanitize_command_text',
        method='_sanitize_command_text',
        class_=event.AppMentionRegisterEvent,
        args=('<@U1234567890> register PROJ-123',),
        expected_result='register PROJ-123',
    ),
    UtilityMethodScenario(
        name='sanitize_command_text',
        method='_sanitize_command_text',
        class_=event.AppMentionRegisterEvent,
        args=('<@U1234567890> <@U0987654321> register PROJ-123',),
        expected_result='register PROJ-123',
    ),
    UtilityMethodScenario(
        name='sanitize_command_text',
        method='_sanitize_command_text',
        class_=event.AppMentionEvent,
        args=('<@U1234567890>',),
        expected_result='',
    ),
    UtilityMethodScenario(
        name='format_text',
        method='_format_text',
        class_=event.ReactionSyncEvent,
        args=('Test comment', 'https://test.slack.com/archives/C1234567890/p1234567890123456'),
        expected_result=(
            '(Originating from [Slack message|https://test.slack.com/archives/C1234567890/'
            'p1234567890123456])\n\nTest comment'
        ),
    ),
]


@pytest.mark.parametrize('test_case', UTILITY_METHOD_SCENARIOS, ids=str)
def test_utility_methods(test_case: UtilityMethodScenario):
    method = test_case.method
    args = test_case.args
    expected_result = test_case.expected_result

    result = getattr(test_case.class_, method)(*args)
    assert result == expected_result


class AttachmentInfo:  # pylint: disable=too-few-public-methods
    def __init__(self, name):
        self.name = name


@dataclass
class ReactionAddedAttachmentScenario(Scenario):
    event_obj: MockReactionAddedEvent

    existing_dynamodb_events: List[dict] = field(default_factory=list)
    existing_attachments: List[dict] = field(default_factory=list)
    existing_text: str = field(default='')
    existing_datetime: datetime = field(
        default=datetime.strptime('2025-01-01 00:00:00', '%Y-%m-%d %H:%M:%S')
    )

    expected_reaction: str = field(default=CONFIG['success_reaction'])
    expected_attachments: List[dict] = field(default_factory=list)
    expected_text: str = field(default='')

    expected_comment_count: int = field(init=False)

    def __post_init__(self):
        self.expected_comment_count = len(self.existing_dynamodb_events)


REACTION_ADDED_ATTACHMENT_SCENARIOS = [
    ReactionAddedAttachmentScenario(
        name='registered_thread_gothic_sync_success_single_attachment',
        event_obj=MockReactionAddedEvent(
            reaction=CONFIG['sync_reaction'],
            channel='C1234567890',
            ts='1234567890.123456',
        ),
        existing_dynamodb_events=[
            {
                'jira_issue_id': 'PROJ-123',
                'slack_thread_id': 'C1234567890_1234567890.123456',
                'jira_link_id': '1234567890',
            }
        ],
        existing_attachments=[
            {
                'name': 'test.png',
                'url': 'https://test.slack.com/messages/test-channel/1234567890.123456',
            }
        ],
        expected_attachments=[{'name': 'test.png'}],
        expected_text='\n\n![test.png|thumbnail!]',
    ),
    ReactionAddedAttachmentScenario(
        name='registered_thread_gothic_sync_success_multiple_attachments',
        event_obj=MockReactionAddedEvent(
            reaction=CONFIG['sync_reaction'],
            channel='C1234567890',
            ts='1234567890.123456',
        ),
        existing_dynamodb_events=[
            {
                'jira_issue_id': 'PROJ-123',
                'slack_thread_id': 'C1234567890_1234567890.123456',
                'jira_link_id': '1234567890',
            }
        ],
        existing_attachments=[
            {
                'name': 'test.png',
                'url': 'https://test.slack.com/messages/test-channel/1234567890.123456',
            },
            {
                'name': 'test.jpg',
                'url': 'https://test.slack.com/messages/test-channel/1234567890.123456',
            },
        ],
        expected_attachments=[{'name': 'test.png'}, {'name': 'test.jpg'}],
        expected_text='\n\n![test.png|thumbnail!]\n\n![test.jpg|thumbnail!]',
    ),
    ReactionAddedAttachmentScenario(
        name='multiple_registered_issues_success',
        event_obj=MockReactionAddedEvent(
            reaction=CONFIG['sync_reaction'],
            channel='C1234567890',
            ts='1234567890.123456',
        ),
        existing_dynamodb_events=[
            {
                'jira_issue_id': 'PROJ-123',
                'slack_thread_id': 'C1234567890_1234567890.123456',
                'jira_link_id': '1234567890',
            },
            {
                'jira_issue_id': 'PROJ-456',
                'slack_thread_id': 'C1234567890_1234567890.123456',
                'jira_link_id': '4567890123',
            },
        ],
        existing_attachments=[
            {
                'name': 'test.png',
                'url': 'https://test.slack.com/messages/test-channel/1234567890.123456',
            },
            {
                'name': 'test.jpg',
                'url': 'https://test.slack.com/messages/test-channel/1234567890.123456',
            },
        ],
        expected_attachments=[{'name': 'test.png'}, {'name': 'test.jpg'}],
        expected_text='\n\n![test.png|thumbnail!]\n\n![test.jpg|thumbnail!]',
    ),
]


@pytest.mark.parametrize('test_case', REACTION_ADDED_ATTACHMENT_SCENARIOS, ids=str)
def test_reaction_added_attachment(processor, test_case: ReactionAddedAttachmentScenario):
    event_dict = test_case.event_obj.event_dict
    existing_text = test_case.existing_text
    existing_attachments = test_case.existing_attachments

    expected_comment_count = test_case.expected_comment_count

    dynamo_db_wrapper = processor.event_factory.dynamo_db_wrapper

    for existing_dynamodb_event in test_case.existing_dynamodb_events:
        dynamo_db_wrapper.put_item(existing_dynamodb_event)

    with ExitStack() as stack:
        reaction_added_mock = stack.enter_context(
            patch.object(processor.event_factory.slack_sdk_wrapper, 'add_reaction')
        )
        comment_added_mock = stack.enter_context(
            patch.object(processor.event_factory.jira_wrapper, 'add_comment')
        )

        stack.enter_context(
            patch.multiple(
                processor.event_factory.slack_sdk_wrapper,
                get_content_from_message_ts=Mock(
                    return_value=(existing_text, existing_attachments)
                ),
                get_thread_ts_from_message_ts=Mock(return_value='1234567890.123456'),
                get_message_link=Mock(
                    return_value='https://test.slack.com/messages/test-channel/1234567890.123456'
                ),
                remove_bot_reactions=Mock(),
            ),
        )

        event_obj = processor.event_factory.create_event(event_dict)

        attach_file_mock = stack.enter_context(
            patch.object(
                event_obj,
                'process_file_attachments',
                return_value=[
                    [''] * len(test_case.existing_attachments)
                    for _ in test_case.existing_dynamodb_events
                ],
            ),
        )

        processor._process(event_obj)

        assert comment_added_mock.call_count == expected_comment_count
        attach_file_mock.assert_called_once()

        if test_case.expected_reaction:
            reaction_added_mock.assert_called_once()
            assert reaction_added_mock.call_args[0][2] == test_case.expected_reaction
        else:
            reaction_added_mock.assert_not_called()


@dataclass
class EventFactoryScenario(Scenario):
    event_obj: MockEvent
    raises: Optional[Exception] = None


EVENT_FACTORY_SCENARIOS = [
    EventFactoryScenario(
        name='app_mention_success',
        event_obj=MockAppMentionEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            text='<@U1234567890> register PROJ-123',
        ),
    ),
    EventFactoryScenario(
        name='app_mention_error',
        event_obj=MockAppMentionEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            text='<@U1234567890> register PROJ-123',
        ),
        # raises=True,
    ),
    EventFactoryScenario(
        name='app_mention_error_invalid_command',
        event_obj=MockAppMentionEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            text='<@U1234567890> register PROJ-123',
        ),
        # raises=True,
    ),
    EventFactoryScenario(
        name='app_mention_error_invalid_command_format',
        event_obj=MockAppMentionEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            text='<@U1234567890> register PROJ-123',
        ),
        # raises=True,
    ),
    EventFactoryScenario(
        name='reaction_added_error',
        event_obj=MockReactionAddedEvent(
            ts='9876543210.987654',
            channel='C1234567890',
            reaction=CONFIG['sync_reaction'],
        ),
        # raises=True,
    ),
]


@pytest.mark.parametrize('test_case', EVENT_FACTORY_SCENARIOS, ids=str)
def test_event_factory(event_factory, test_case: EventFactoryScenario):

    with ExitStack() as stack:
        stack.enter_context(
            patch.multiple(
                event_factory.slack_sdk_wrapper,
                get_channel_name=Mock(return_value='test-channel'),
                get_message_link=Mock(
                    return_value='https://test.slack.com/messages/test-channel/1234567890.123456'
                ),
            )
        )
        event_dict = test_case.event_obj.event_dict
        if test_case.raises:
            with pytest.raises(Exception):
                event_factory.create_event(event_dict)
        else:
            event_factory.create_event(event_dict)


@dataclass
class RegisterEventJiraLinkScenario(Scenario):
    event_obj: MockAppMentionRegisterEvent
    channel_name: str
    thread_link: str
    expected_jira_call: str
    existing_link: bool = False
    expected_args: Tuple[Any, ...] = field(init=False)
    expected_kwargs: Dict[str, Any] = field(init=False)

    expected_jira_issue_id: Optional[str] = None
    expected_link_text: Optional[str] = None

    def __post_init__(self):
        if not self.expected_jira_issue_id:
            self.expected_jira_issue_id = self.event_obj.jira_issue_id

        if not self.expected_link_text:
            self.expected_link_text = self.event_obj.link_text

        self.expected_args = (
            self.expected_jira_issue_id,
            self.thread_link,
            event.AppMentionRegisterEvent._get_link_title(
                self.channel_name,
                self.expected_link_text if self.expected_link_text else self.event_obj.thread_ts,
            ),
        )
        self.expected_kwargs = {
            'icon_url': CONFIG['icon_url'],
            'icon_title': CONFIG['icon_title'],
        }


REGISTER_EVENT_JIRA_LINK_SCENARIOS = [
    RegisterEventJiraLinkScenario(
        name='register_event_jira_link',
        event_obj=MockAppMentionRegisterEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            jira_issue_id='PROJ-123',
            link_text='',
        ),
        channel_name='test-channel',
        thread_link='https://test.slack.com/messages/test-channel/1234567890.123456',
        expected_jira_call='create_or_update_issue_remote_links',
    ),
    RegisterEventJiraLinkScenario(
        name='register_event_jira_link_with link text',
        event_obj=MockAppMentionRegisterEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            jira_issue_id='PROJ-123',
            link_text='Custom Link Text',
        ),
        channel_name='test-channel',
        thread_link='https://test.slack.com/messages/test-channel/1234567890.123456',
        expected_jira_call='create_or_update_issue_remote_links',
    ),
    RegisterEventJiraLinkScenario(
        name='register_event_jira_ticket_with_link',
        event_obj=MockAppMentionRegisterEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            jira_issue_id=r'<https://example.com|PROJ-123>',
        ),
        channel_name='test-channel',
        thread_link='https://test.slack.com/messages/test-channel/1234567890.123456',
        expected_jira_call='create_or_update_issue_remote_links',
        expected_jira_issue_id='PROJ-123',
    ),
    RegisterEventJiraLinkScenario(
        name='register_event_jira_ticket_with_link_text_and_http_link',
        event_obj=MockAppMentionRegisterEvent(
            ts='9876543210.987654',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            jira_issue_id=r'<https://example.com|PROJ-123>',
            link_text=r'<https://example.com>',
        ),
        channel_name='test-channel',
        thread_link='https://test.slack.com/messages/test-channel/1234567890.123456',
        expected_jira_call='create_or_update_issue_remote_links',
        expected_jira_issue_id='PROJ-123',
        expected_link_text='https://example.com',
    ),
]


@pytest.mark.parametrize('test_case', REGISTER_EVENT_JIRA_LINK_SCENARIOS, ids=str)
def test_register_event_jira_link(processor, test_case: RegisterEventJiraLinkScenario):
    event_dict = test_case.event_obj.event_dict
    expected_jira_call = test_case.expected_jira_call
    expected_args = test_case.expected_args
    expected_kwargs = test_case.expected_kwargs

    with ExitStack() as stack:
        stack.enter_context(
            patch.multiple(
                processor.event_factory.slack_sdk_wrapper,
                get_channel_name=Mock(return_value=test_case.channel_name),
                get_message_link=Mock(return_value=test_case.thread_link),
                remove_bot_reactions=Mock(),
            )
        )

        mock_jira_call = stack.enter_context(
            patch.object(processor.event_factory.jira_wrapper.jira, expected_jira_call)
        )

        processor.process(event_dict)
        assert mock_jira_call.call_count == 1
        mock_jira_call.assert_called_with(*expected_args, **expected_kwargs)


@dataclass
class AsyncTransferScenario(Scenario):
    files: List[dict] = field(default_factory=list)
    jira_issue_ids: List[str] = field(default_factory=list)
    file_contents: Dict[str, bytes] = field(default_factory=dict)
    expected_uploads: Dict[str, List[str]] = field(default_factory=dict)
    upload_failures: Dict[str, List[str]] = field(default_factory=dict)
    download_failure: Optional[str] = None
    expected_markup_count: int = field(init=False)

    def __post_init__(self):
        self.expected_markup_count = len(self.files) * len(self.jira_issue_ids)


ASYNC_TRANSFER_SCENARIOS = [
    AsyncTransferScenario(
        name='single_file_single_jira',
        files=[{'name': 'test.png', 'url': 'https://files.slack.com/test.png'}],
        jira_issue_ids=['PROJ-123'],
        file_contents={'https://files.slack.com/test.png': b'fake_png_data'},
        expected_uploads={'PROJ-123': ['test.png']},
    ),
    AsyncTransferScenario(
        name='single_file_multiple_jiras',
        files=[{'name': 'document.pdf', 'url': 'https://files.slack.com/document.pdf'}],
        jira_issue_ids=['PROJ-123', 'PROJ-456', 'PROJ-789'],
        file_contents={'https://files.slack.com/document.pdf': b'fake_pdf_data'},
        expected_uploads={
            'PROJ-123': ['document.pdf'],
            'PROJ-456': ['document.pdf'],
            'PROJ-789': ['document.pdf'],
        },
    ),
    AsyncTransferScenario(
        name='multiple_files_single_jira',
        files=[
            {'name': 'image.jpg', 'url': 'https://files.slack.com/image.jpg'},
            {'name': 'report.pdf', 'url': 'https://files.slack.com/report.pdf'},
        ],
        jira_issue_ids=['PROJ-123'],
        file_contents={
            'https://files.slack.com/image.jpg': b'fake_jpg_data',
            'https://files.slack.com/report.pdf': b'fake_pdf_data',
        },
        expected_uploads={'PROJ-123': ['image.jpg', 'report.pdf']},
    ),
    AsyncTransferScenario(
        name='multiple_files_multiple_jiras',
        files=[
            {'name': 'photo.png', 'url': 'https://files.slack.com/photo.png'},
            {'name': 'data.csv', 'url': 'https://files.slack.com/data.csv'},
        ],
        jira_issue_ids=['PROJ-123', 'PROJ-456'],
        file_contents={
            'https://files.slack.com/photo.png': b'fake_png_data',
            'https://files.slack.com/data.csv': b'fake_csv_data',
        },
        expected_uploads={
            'PROJ-123': ['photo.png', 'data.csv'],
            'PROJ-456': ['photo.png', 'data.csv'],
        },
    ),
]


@pytest.mark.parametrize('test_case', ASYNC_TRANSFER_SCENARIOS, ids=str)
@pytest.mark.asyncio
async def test_async_slack_to_jira_transfer(test_case: AsyncTransferScenario):
    slack_token = 'test_slack_token'
    jira_token = 'test_jira_token'
    jira_server_url = JIRA_SERVER_URL
    channel_id = 'C1234567890'
    message_ts = '1234567890.123456'

    transfer = AsyncSlackToJiraTransfer(
        slack_token=slack_token,
        jira_token=jira_token,
        jira_server_url=jira_server_url,
        channel_id=channel_id,
        message_ts=message_ts,
    )

    class MockGetResponse:
        def __init__(self, url):
            self._url = url
            self._content = test_case.file_contents.get(url, b'')

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def raise_for_status(self):
            if test_case.download_failure and self._url == test_case.download_failure:
                raise aiohttp.ClientError(f"Failed to download {self._url}")

        @property
        def content(self):
            class ContentReader:  # pylint: disable=too-few-public-methods
                def __init__(self, data):
                    self._data = data

                async def iter_chunked(self, chunk_size):
                    for i in range(0, len(self._data), chunk_size):
                        yield self._data[i : i + chunk_size]

            return ContentReader(self._content)

    class MockPostResponse:
        def __init__(self, url):
            self._url = url

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def raise_for_status(self):
            for issue_id, _ in test_case.upload_failures.items():
                if issue_id in self._url:
                    raise aiohttp.ClientError(f"Upload failed to {issue_id}")

        async def read(self):
            return b'{"id": "12345"}'

    class MockSession:
        def __init__(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, **kwargs):
            return MockGetResponse(url)

        def post(self, url, **kwargs):
            return MockPostResponse(url)

    with patch('aiohttp.ClientSession', MockSession):
        results = await transfer.transfer(test_case.files, test_case.jira_issue_ids)

        assert len(results) == len(test_case.files)
        for file_result in results:
            assert len(file_result) == len(test_case.jira_issue_ids)

        for file_idx, file in enumerate(test_case.files):
            for jira_idx, jira_id in enumerate(test_case.jira_issue_ids):
                markup = results[file_idx][jira_idx]

                if test_case.download_failure or jira_id in test_case.upload_failures:
                    assert markup == ''
                else:
                    filename = file['name']
                    if filename.endswith(('.png', '.jpg', '.jpeg', '.gif')):
                        assert '|thumbnail!' in markup
                    else:
                        assert '[^' in markup and ']' in markup
                    assert filename.split('.')[0] in markup


@dataclass
class MarkupGenerationScenario(Scenario):
    filename: str
    expected_markup_contains: List[str]
    expected_markup_type: str  # 'thumbnail' or 'attachment'


MARKUP_GENERATION_SCENARIOS = [
    MarkupGenerationScenario(
        name='png_image',
        filename='photo.png',
        expected_markup_contains=['photo.png', '|thumbnail!', '!'],
        expected_markup_type='thumbnail',
    ),
    MarkupGenerationScenario(
        name='jpg_image',
        filename='image.jpg',
        expected_markup_contains=['image.jpg', '|thumbnail!', '!'],
        expected_markup_type='thumbnail',
    ),
    MarkupGenerationScenario(
        name='jpeg_image',
        filename='picture.jpeg',
        expected_markup_contains=['picture.jpeg', '|thumbnail!', '!'],
        expected_markup_type='thumbnail',
    ),
    MarkupGenerationScenario(
        name='gif_image',
        filename='animation.gif',
        expected_markup_contains=['animation.gif', '|thumbnail!', '!'],
        expected_markup_type='thumbnail',
    ),
    MarkupGenerationScenario(
        name='pdf_document',
        filename='report.pdf',
        expected_markup_contains=['report.pdf', '[^', ']'],
        expected_markup_type='attachment',
    ),
    MarkupGenerationScenario(
        name='text_file',
        filename='data.txt',
        expected_markup_contains=['data.txt', '[^', ']'],
        expected_markup_type='attachment',
    ),
    MarkupGenerationScenario(
        name='csv_file',
        filename='spreadsheet.csv',
        expected_markup_contains=['spreadsheet.csv', '[^', ']'],
        expected_markup_type='attachment',
    ),
]


@pytest.mark.parametrize('test_case', MARKUP_GENERATION_SCENARIOS, ids=str)
def test_filename_to_jira_markup(test_case: MarkupGenerationScenario):
    markup = AsyncSlackToJiraTransfer.filename_to_jira_markup(test_case.filename)

    for expected in test_case.expected_markup_contains:
        assert expected in markup, f"Expected '{expected}' in markup '{markup}'"

    if test_case.expected_markup_type == 'thumbnail':
        assert markup.startswith('!')
        assert '|thumbnail!' in markup
    else:
        assert markup.startswith('[^')
        assert markup.endswith(']')


@dataclass
class SlackSdkWrapperRetryScenario(Scenario):
    retry_type: Any
    handler: Callable


SLACK_SDK_WRAPPER_RETRY_SCENARIOS = [
    SlackSdkWrapperRetryScenario(
        name='rate_limit_error',
        retry_type=RateLimitErrorRetryHandler,
        handler=lambda: {
            'status': 429,
            'body': json.dumps({'ok': False, 'error': 'rate_limit_error'}),
            'headers': {'Retry-After': '0'},
        },
    ),
    SlackSdkWrapperRetryScenario(
        name='connection_error',
        retry_type=ConnectionErrorRetryHandler,
        handler=lambda: URLError('connection_error'),
    ),
]


@pytest.mark.parametrize('test_case', SLACK_SDK_WRAPPER_RETRY_SCENARIOS, ids=str)
def test_slack_sdk_wrapper_retries_on_rate_limit(test_case: SlackSdkWrapperRetryScenario):
    slack_token = 'xoxb-test-token'
    test_channel = 'test-channel'

    def mock_urllib_api_call(*args, **kwargs):
        api_url = args[1]

        if (
            'auth' not in api_url
            and mock_urllib_api_call.conversations_attempt_count < mock_urllib_api_call.max_retries
        ):
            mock_urllib_api_call.conversations_attempt_count += 1
            returned = test_case.handler()
            if isinstance(returned, Exception):
                raise returned

            return returned

        return {
            'status': 200,
            'body': json.dumps({'ok': True, 'channel': {'name': test_channel}}),
            'headers': {},
        }

    with patch(
        'slack_sdk.web.base_client.BaseClient._perform_urllib_http_request_internal',
        mock_urllib_api_call,
    ):
        wrapper = SlackSdkWrapper(slack_token=slack_token)
        client = wrapper.client
        retries = 0
        for retry_handler in client.retry_handlers:
            if isinstance(retry_handler, test_case.retry_type):
                retries = retry_handler.max_retry_count
                mock_urllib_api_call.max_retries = retries  # type: ignore
                mock_urllib_api_call.conversations_attempt_count = 0  # type: ignore
                break

        assert retries > 0
        result = wrapper.get_channel_name('C12345')

        assert mock_urllib_api_call.conversations_attempt_count == retries  # type: ignore
        assert result == test_channel


def test_jira_wrapper_retries_on_rate_limit_error():
    max_retries = 2
    comment_id = '12345'

    def mock_request(*args, **kwargs):
        mock_request.attempt_count += 1
        mock_response = requests.Response()

        if mock_request.attempt_count <= max_retries:
            mock_response.status_code = 429
            mock_response._content = json.dumps({'error': 'rate_limit_error'}).encode('utf-8')
            mock_response.headers = {'Retry-After': '0'}
        else:
            mock_response.status_code = 200
            mock_response._content = json.dumps({'id': comment_id}).encode('utf-8')

        return mock_response

    mock_request.attempt_count = 0

    wrapper = JiraWrapper(server_url=JIRA_SERVER_URL, jira_token=JIRA_TOKEN)
    wrapper.jira._session.request = mock_request

    result = wrapper.add_comment('PROJ-123', 'Test comment')

    assert mock_request.attempt_count == max_retries + 1
    assert result == comment_id
