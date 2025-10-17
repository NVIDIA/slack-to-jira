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
DynamoDB wrapper module for simplified DynamoDB operations.

This module provides a simplified interface for common DynamoDB operations
including put, get, delete, and query operations. It wraps the boto3 DynamoDB
resource to provide a simpler API for basic database interactions.
'''

from __future__ import annotations

import boto3
from boto3.dynamodb.conditions import Key


class DynamoDbWrapper:
    '''
    A wrapper class for DynamoDB operations.

    This class provides a simplified interface for common DynamoDB operations
    including item creation, retrieval, deletion, and querying. It abstracts
    away the complexity of boto3 DynamoDB resource management.

    Attributes:
        dynamodb: The boto3 DynamoDB resource instance.
        table: The DynamoDB table instance for the specified table name.
    '''

    def __init__(self, table_name: str) -> None:
        '''
        Initialize the DynamoDB wrapper with a specific table.

        Args:
            table_name: The name of the DynamoDB table to interact with.
        '''
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(table_name)

    def put_item(self, item: dict) -> None:
        '''
        Put an item into the DynamoDB table.

        Args:
            item: The item to store in the table. Must contain the
                  primary key attributes and any other attributes to store.
        '''
        self.table.put_item(Item=item)

    def get_item(self, key: dict) -> dict:
        '''
        Retrieve an item from the DynamoDB table.

        Args:
            key: The primary key of the item to retrieve.

        Returns:
            The item if found, empty dictionary if the item doesn't exist.
        '''
        response = self.table.get_item(
            Key=key,
        )
        return response.get('Item', {})

    def delete_item(self, key: dict) -> None:
        '''
        Delete an item from the DynamoDB table.

        Args:
            key: The primary key of the item to delete.
        '''
        self.table.delete_item(Key=key)

    def query(self, key: str, key_value: str) -> list[dict]:
        '''
        Query items from the DynamoDB table using a key condition.

        Args:
            key: The name of the key attribute to query on.
            key_value: The value to match for the key attribute.

        Returns:
            A list of items that match the query condition.
        '''
        response = self.table.query(KeyConditionExpression=Key(key).eq(key_value))
        items = response.get('Items', [])

        last_evaluated_key: dict | None = response.get('LastEvaluatedKey')
        while last_evaluated_key:
            response = self.table.query(
                KeyConditionExpression=Key(key).eq(key_value),
                ExclusiveStartKey=last_evaluated_key,
            )
            items.extend(response.get('Items', []))
            last_evaluated_key = response.get('LastEvaluatedKey')

        return items
