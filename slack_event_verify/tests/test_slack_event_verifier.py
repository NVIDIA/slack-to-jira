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
import base64
from enum import Enum
import json
import os
import time
import hmac
import hashlib
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

import boto3
from moto import mock_aws
import pytest

os.environ['SUCCESS_REACTION'] = 'tick'
os.environ['ERROR_REACTION'] = 'x'
os.environ['ICON_URL'] = 'https://example.com/icon.png'
os.environ['ICON_TITLE'] = 'Test Icon'
os.environ['SYNC_REACTION'] = 'sync'
os.environ['APP_NAME'] = 'app-name'

# pylint:disable=wrong-import-position
import event  # pylint:disable=unused-import
from event.config import CONFIG

from secrets_manager_wrapper import SecretsManagerWrapper
from sqs_wrapper import SqsWrapper
from slack_sdk_wrapper import SlackSdkWrapper

from slack_event_verify.slack_event_verifier import SlackEventVerifier


SIGNING_SECRET_ID = 'test-signing-secret'
SIGNING_SECRET_VALUE = 'test_signing_secret_value'
SQS_QUEUE_NAME = 'test-queue.fifo'
SQS_QUEUE_URL = f'https://sqs.us-east-1.amazonaws.com/123456789012/{SQS_QUEUE_NAME}'


def create_slack_signature(body: str, signing_secret: str, timestamp: Optional[str] = None) -> str:
    '''
    Create a valid Slack signature for testing.

    Args:
        body: The request body as a string
        signing_secret: The Slack app signing secret
        timestamp: Optional timestamp (defaults to current time)

    Returns:
        A valid Slack signature string
    '''
    if timestamp is None:
        timestamp = str(int(time.time()))

    sig_basestring = f'v0:{timestamp}:{body}'

    signature = hmac.new(
        signing_secret.encode('utf-8'), sig_basestring.encode('utf-8'), hashlib.sha256
    ).hexdigest()

    return f'v0={signature}'


def create_slack_headers(body: str, signing_secret: str, timestamp: Optional[str] = None) -> dict:
    '''
    Create valid Slack headers for testing.

    Args:
        body: The request body as a string
        signing_secret: The Slack app signing secret
        timestamp: Optional timestamp (defaults to current time)

    Returns:
        A dictionary with valid Slack headers
    '''
    if timestamp is None:
        timestamp = str(int(time.time()))

    signature = create_slack_signature(body, signing_secret, timestamp)

    return {
        'X-Slack-Request-Timestamp': timestamp,
        'X-Slack-Signature': signature,
        'Content-Type': 'application/json',
    }


@pytest.fixture()
def aws_setup():
    with mock_aws():
        os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
        yield


@pytest.fixture
def slack_sdk_wrapper():
    return SlackSdkWrapper()


@pytest.fixture(autouse=True)
def secrets_manager(aws_setup):
    mock_secrets_manager = boto3.client('secretsmanager')
    mock_secrets_manager.create_secret(Name=SIGNING_SECRET_ID, SecretString=SIGNING_SECRET_VALUE)
    return mock_secrets_manager


@pytest.fixture(autouse=True)
def sqs_client(aws_setup):
    mock_sqs_client = boto3.client('sqs')
    mock_sqs_client.create_queue(
        QueueName=SQS_QUEUE_NAME,
        Attributes={'FifoQueue': 'true', 'ContentBasedDeduplication': 'true'},
    )
    return mock_sqs_client


@pytest.fixture()
def secrets_manager_wrapper(aws_setup):
    return SecretsManagerWrapper()


@pytest.fixture()
def sqs_wrapper(aws_setup):
    return SqsWrapper()


@pytest.fixture
def verifier(slack_sdk_wrapper, secrets_manager_wrapper, sqs_wrapper):
    return SlackEventVerifier(
        slack_sdk_wrapper=slack_sdk_wrapper,
        secrets_manager_wrapper=secrets_manager_wrapper,
        sqs_wrapper=sqs_wrapper,
        signing_secret_id=SIGNING_SECRET_ID,
        sqs_queue_url=SQS_QUEUE_URL,
    )


class EventType(Enum):
    APP_MENTION = 'app_mention'
    REACTION_ADDED = 'reaction_added'
    URL_VERIFICATION = 'url_verification'
    INVALID = 'invalid'


@dataclass
class MockEvent:
    event_type: EventType = field(default=EventType.INVALID)
    event_dict: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MockAppMentionEvent(MockEvent):
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
class MockReactionAddedEvent(MockEvent):
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
class MockVerificationEvent(MockEvent):
    challenge: Optional[str] = None

    def __post_init__(self):
        self.event_type = EventType.URL_VERIFICATION
        self.event_dict = {
            'challenge': self.challenge,
            'type': self.event_type.value,
        }
        self.event_dict = {k: v for k, v in self.event_dict.items() if v is not None}


@dataclass
class EventContainer:
    event_obj: Optional[MockEvent] = None
    headers: Optional[dict] = None
    is_base64_encoded: bool = False

    def __post_init__(self):
        if self.event_obj:
            self.body = {}
            # NOTE: This is not a deep copy!
            if self.event_obj.event_type in [EventType.URL_VERIFICATION, EventType.INVALID]:
                self.body = self.event_obj.event_dict
            else:
                self.body['event'] = self.event_obj.event_dict
                self.body['type'] = 'event_callback'

            if self.event_obj.event_type != EventType.INVALID or isinstance(self.body, dict):
                self.body = json.dumps(self.body)
        else:
            self.body = None

        if self.headers is None:
            self.headers = create_slack_headers(self.body, SIGNING_SECRET_VALUE)

        if self.is_base64_encoded:
            self.body = base64.b64encode(self.body.encode('utf-8')).decode('utf-8')

    def to_dict(self):
        dict_event = {}
        if self.body:
            dict_event['body'] = self.body

        if self.headers is not False:
            dict_event['headers'] = self.headers

        dict_event['isBase64Encoded'] = self.is_base64_encoded

        return dict_event


@dataclass
class Scenario(ABC):
    name: str

    def __init__(self, name: str):
        self.name = name

    def __str__(self):
        return self.name


@dataclass
class MockUtilityScenario(Scenario):
    event_obj: MockEvent
    expected_result: Optional[str] = None


MOCK_CONSTRUCT_EVENT_MESSAGE_GROUP_SCENARIOS = [
    MockUtilityScenario(
        name='construct_event_message_group_reaction_added',
        event_obj=MockReactionAddedEvent(
            reaction=CONFIG['sync_reaction'], channel='C1234567890', ts='1234567890.123456'
        ),
        expected_result='C1234567890_1234567890.123456',
    ),
    MockUtilityScenario(
        name='construct_event_message_group_app_mention',
        event_obj=MockAppMentionEvent(
            ts='1234567890.123457',
            thread_ts='1234567890.123457',
            channel='C1234567890',
            text='<@U1234567890> register PROJ-123',
        ),
        expected_result='C1234567890_1234567890.123457',
    ),
]


@pytest.mark.parametrize('test_case', MOCK_CONSTRUCT_EVENT_MESSAGE_GROUP_SCENARIOS, ids=str)
def test_construct_event_message_group(verifier, test_case):
    result = (
        event.EventFactory(verifier.slack_sdk_wrapper, None, None)
        .create_event(test_case.event_obj.event_dict)
        .construct_message_group_id()
    )
    assert result == test_case.expected_result


@dataclass
class VerifyReturnDataScenario(Scenario):
    event_obj: EventContainer
    expected_result: dict


MOCK_VERIFY_RETURN_DATA_SCENARIOS = [
    VerifyReturnDataScenario(
        name='verify_missing_headers_or_body',
        event_obj=EventContainer(headers={}, event_obj=MockEvent(event_dict={})),
        expected_result={
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json'},
            'body': 'Bad Request',
        },
    ),
    VerifyReturnDataScenario(
        name='verify_missing_headers',
        event_obj=EventContainer(headers={}, event_obj=MockEvent(event_dict={'test': 'data'})),
        expected_result={
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json'},
            'body': 'Bad Request',
        },
    ),
    VerifyReturnDataScenario(
        name='verify_missing_body',
        event_obj=EventContainer(headers={'X-Slack-Signature': 'test'}),
        expected_result={
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json'},
            'body': 'Bad Request',
        },
    ),
    VerifyReturnDataScenario(
        name='verify_invalid_request',
        event_obj=EventContainer(
            headers={'X-Slack-Signature': 'test'}, event_obj=MockEvent(event_dict={'test': 'data'})
        ),
        expected_result={
            'statusCode': 403,
            'headers': {'Content-Type': 'application/json'},
            'body': 'Forbidden',
        },
    ),
    VerifyReturnDataScenario(
        name='verify_url_verification',
        event_obj=EventContainer(
            event_obj=MockVerificationEvent(challenge='test_challenge_string')
        ),
        expected_result={
            'statusCode': 200,
            'headers': {'Content-Type': 'text/plain'},
            'body': 'test_challenge_string',
        },
    ),
]


@pytest.mark.parametrize('test_case', MOCK_VERIFY_RETURN_DATA_SCENARIOS, ids=str)
def test_verify_return_data(verifier, test_case):
    result = verifier.verify(test_case.event_obj.to_dict())
    assert result['statusCode'] == test_case.expected_result['statusCode']
    assert result['headers']['Content-Type'] == test_case.expected_result['headers']['Content-Type']

    if result['headers']['Content-Type'] == 'application/json':
        body_json = json.loads(result['body'])
        if 'message' in body_json:
            assert body_json['message'] == test_case.expected_result['body']
        else:
            assert body_json == test_case.expected_result['body']
    else:
        assert result['body'] == test_case.expected_result['body']


@dataclass
class VerifyGeneralScenario(Scenario):
    event_obj: EventContainer
    expected_result: Optional[dict] = None
    raises: Optional[type[Exception]] = None


MOCK_VERIFY_GENERAL_SCENARIOS = [
    VerifyGeneralScenario(
        name='verify_url_verification_base64_encoded',
        event_obj=EventContainer(
            event_obj=MockVerificationEvent(challenge='test_challenge_string'),
            is_base64_encoded=True,
        ),
        expected_result={
            'statusCode': 200,
            'headers': {'Content-Type': 'text/plain'},
            'body': 'test_challenge_string',
        },
    ),
    VerifyGeneralScenario(
        name='verify_reaction_added_event',
        event_obj=EventContainer(
            event_obj=MockReactionAddedEvent(
                reaction=CONFIG['sync_reaction'], channel='C1234567890', ts='1234567890.123456'
            ),
            is_base64_encoded=True,
        ),
        expected_result={
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': 'Success',
        },
    ),
    VerifyGeneralScenario(
        name='verify_app_mention_event',
        event_obj=EventContainer(
            event_obj=MockAppMentionEvent(
                ts='1234567890.123457',
                thread_ts='1234567890.123457',
                channel='C1234567890',
                text='<@U1234567890> register PROJ-123',
            ),
            is_base64_encoded=True,
        ),
        expected_result={
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': 'Success',
        },
    ),
    VerifyGeneralScenario(
        name='verify_unhandled_event_type',
        event_obj=EventContainer(
            event_obj=MockEvent(event_dict={'type': 'message', 'channel': 'C1234567890'}),
            is_base64_encoded=True,
        ),
        expected_result={
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json'},
            'body': 'Bad Request',
        },
    ),
    VerifyGeneralScenario(
        name='verify_missing_event_type',
        event_obj=EventContainer(event_obj=MockEvent(event_dict={}), is_base64_encoded=True),
        expected_result={
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json'},
            'body': 'Bad Request',
        },
    ),
    VerifyGeneralScenario(
        name='verify_missing_event',
        event_obj=EventContainer(event_obj=MockEvent(event_dict={}), is_base64_encoded=True),
        expected_result={
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json'},
            'body': 'Bad Request',
        },
    ),
    VerifyGeneralScenario(
        name='verify_invalid_json_body',
        event_obj=EventContainer(event_obj=MockEvent(event_dict='invalid json')),  # type: ignore
        raises=json.JSONDecodeError,
    ),
    VerifyGeneralScenario(
        name='verify_empty_event_type',
        event_obj=EventContainer(
            event_obj=MockEvent(event_dict={'type': '', 'channel': 'C1234567890'}),
            is_base64_encoded=True,
        ),
        expected_result={
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json'},
            'body': 'Bad Request',
        },
    ),
    VerifyGeneralScenario(
        name='verify_none_event_type',
        event_obj=EventContainer(
            event_obj=MockEvent(event_dict={'type': None, 'channel': 'C1234567890'}),
            is_base64_encoded=True,
        ),
        expected_result={
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json'},
            'body': 'Bad Request',
        },
    ),
    VerifyGeneralScenario(
        name='verify_construct_event_message_group_with_missing_fields',
        event_obj=EventContainer(
            event_obj=MockEvent(event_dict={'type': 'reaction_added'}), is_base64_encoded=True
        ),
        expected_result={
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json'},
            'body': 'Bad Request',
        },
    ),
]


@pytest.mark.parametrize('test_case', MOCK_VERIFY_GENERAL_SCENARIOS, ids=str)
def test_verify_general(verifier, test_case):
    if test_case.raises:
        with pytest.raises(test_case.raises):
            verifier.verify(test_case.event_obj.to_dict())

        return

    assert test_case.expected_result is not None

    result = verifier.verify(test_case.event_obj.to_dict())
    assert result['statusCode'] == test_case.expected_result['statusCode']
    assert result['headers']['Content-Type'] == test_case.expected_result['headers']['Content-Type']

    if result['headers']['Content-Type'] == 'application/json':
        body_json = json.loads(result['body'])
        if 'message' in body_json:
            assert body_json['message'] == test_case.expected_result['body']
        else:
            assert body_json == test_case.expected_result['body']
    else:
        assert result['body'] == test_case.expected_result['body']


@dataclass
class VerifyMessageSentScenario(Scenario):
    event_obj: EventContainer


VERIFY_MESSAGE_SENT_SCENARIOS = [
    VerifyMessageSentScenario(
        name='verify_reaction_added',
        event_obj=EventContainer(
            event_obj=MockReactionAddedEvent(
                reaction=CONFIG['sync_reaction'], channel='C1234567890', ts='1234567890.123456'
            )
        ),
    ),
    VerifyMessageSentScenario(
        name='verify_app_mention',
        event_obj=EventContainer(
            event_obj=MockAppMentionEvent(
                channel='C1234567890',
                ts='1234567890.123457',
                thread_ts='1234567890.123457',
                text='<@U1234567890> register PROJ-123',
            )
        ),
    ),
]


@pytest.mark.parametrize('test_case', VERIFY_MESSAGE_SENT_SCENARIOS, ids=str)
def test_verify_message_sent(sqs_client, verifier, test_case):
    result = verifier.verify(test_case.event_obj.to_dict())

    assert result['statusCode'] == 200

    messages = sqs_client.receive_message(QueueUrl=SQS_QUEUE_URL)
    assert 'Messages' in messages
    assert len(messages['Messages']) == 1

    message_body = json.loads(messages['Messages'][0]['Body'])
    assert message_body == json.loads(test_case.event_obj.to_dict()['body'])
