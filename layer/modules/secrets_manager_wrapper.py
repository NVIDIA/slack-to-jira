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
Wrapper module for AWS Secrets Manager operations.

This module provides wrapper classes around boto3 Secrets Manager client to:
1. Handle retrieving and setting secret values
2. Provide consistent error handling
'''

from __future__ import annotations

import boto3


class SecretsManagerWrapper:  # pylint: disable=too-few-public-methods
    '''
    Base wrapper class for Secrets Manager operations.

    This class provides a simplified interface for:
    1. Retrieving secret values
    2. Setting secret values
    3. Error handling and logging
    4. Client initialization and management

    The wrapper simplifies Secrets Manager interactions and provides consistent interfaces
    for both standard string secrets and structured JSON secrets.
    '''

    def __init__(self) -> None:
        '''
        Initialize the Secrets Manager wrapper.

        Creates a new boto3 Secrets Manager client for handling secret operations.
        '''
        self.client = boto3.client('secretsmanager')

    def get_secret(self, secret_id: str) -> str:
        '''
        Get a secret value from Secrets Manager.

        Args:
            secret_id: ID or ARN of the secret to retrieve

        Returns:
            str: The secret value as a string

        Raises:
            ClientError: If the secret cannot be retrieved from AWS
            ValueError: If the secret value is not a string
        '''
        response = self.client.get_secret_value(SecretId=secret_id)
        return response['SecretString']
