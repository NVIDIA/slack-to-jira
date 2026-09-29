# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
Jira wrapper module for simplified Jira operations.

This module provides a simplified interface for common Jira operations
including adding/removing links, comments, and managing remote links.
'''

from __future__ import annotations

from typing import Optional

import requests
from atlassian import Jira


class JiraWrapper:
    '''
    A wrapper class for Jira operations.

    This class provides a simplified interface for common Jira operations
    including link management, comments, and remote link operations.
    '''

    def __init__(
        self,
        server_url: Optional[str] = None,
        jira_email: Optional[str] = None,
        jira_token: Optional[str] = None,
    ) -> None:
        if server_url and jira_email and jira_token:
            self.jira_email = jira_email
            self.jira_token = jira_token
            self.server_url = server_url
            self.jira = Jira(
                url=server_url,
                username=jira_email,
                password=jira_token,
                cloud=True,
                api_version='3',
                backoff_and_retry=True,
                backoff_jitter=0.2,
                max_backoff_seconds=2,
                max_backoff_retries=3,
                retry_with_header=True,
            )

    def add_link(
        self, jira_issue_id: str, url: str, title: str, icon_url: str, icon_title: str
    ) -> str:
        '''
        Add a link to a Jira issue.

        Args:
            jira_issue_id: The ID of the Jira issue.
            url: The URL to link to.
            title: The title of the link.
            icon_url: The URL of the icon for the link.
            icon_title: The title of the icon.

        Returns:
            The ID of the created link.

        Raises:
            RuntimeError: If Jira does not return a link id. The HTTP status and
                body are included, because a 2xx with an empty or null body does
                not mean the link was created.
        '''
        # advanced_mode keeps the raw response. The default parser turns an empty
        # or null body into None and discards the status code.
        previous_advanced_mode = getattr(self.jira, 'advanced_mode', False)
        self.jira.advanced_mode = True
        try:
            response = self.jira.create_or_update_issue_remote_links(
                jira_issue_id,
                url,
                title,
                icon_url=icon_url,
                icon_title=icon_title,
            )
        finally:
            self.jira.advanced_mode = previous_advanced_mode

        if isinstance(response, requests.Response):
            return self._remote_link_id_from_response(jira_issue_id, response)

        # Test doubles and older call sites return the parsed JSON object.
        if isinstance(response, dict) and response.get('id') is not None:
            return response['id']

        raise RuntimeError(
            f'Jira did not return a remote link id for {jira_issue_id}. Response: {response!r}'
        )

    def _remote_link_id_from_response(self, jira_issue_id: str, response: requests.Response) -> str:
        '''
        Read a remote link id from a raw Jira response.

        Args:
            jira_issue_id: The ID of the Jira issue.
            response: The raw HTTP response from creating the remote link.

        Returns:
            The ID of the created link.

        Raises:
            requests.exceptions.HTTPError: If Jira returned an error status.
            RuntimeError: If a non-error response does not contain a link id.
        '''
        if response.status_code >= 400:
            self.jira.raise_for_status(response)

        try:
            body = response.json()
        except ValueError:
            body = None

        if isinstance(body, dict) and body.get('id') is not None:
            return body['id']

        raise RuntimeError(
            f'Jira did not create a remote link on {jira_issue_id}: '
            f'HTTP {response.status_code} {response.text!r}'
        )

    def remove_link(self, jira_issue_id: str, jira_link_id: str) -> None:
        '''
        Remove a link from a Jira issue.

        Args:
            jira_issue_id: The ID of the Jira issue.
            jira_link_id: The ID of the Jira link to remove.
        '''
        try:
            self.jira.delete_issue_remote_link_by_id(jira_issue_id, jira_link_id)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code != 404:
                raise

    def add_comment(self, jira_issue_id: str, comment: str | dict) -> str:
        '''
        Add a comment to a Jira issue.

        Args:
            jira_issue_id: The ID of the Jira issue.
            comment: The comment text to add.

        Returns:
            The ID of the created comment.
        '''
        result = self.jira.post(
            f'rest/api/3/issue/{jira_issue_id}/comment',
            data={'body': comment if isinstance(comment, dict) else self._text_document(comment)},
        )
        return result['id']

    @staticmethod
    def _text_document(comment: str) -> dict:
        '''
        Wrap plain text in an Atlassian Document Format document.

        Args:
            comment: Comment text. Line breaks are preserved.

        Returns:
            ADF document.
        '''
        return {
            'type': 'doc',
            'version': 1,
            'content': [
                {
                    'type': 'paragraph',
                    'content': JiraWrapper._text_content(comment),
                }
            ],
        }

    @staticmethod
    def _text_content(text: str) -> list[dict]:
        '''
        Convert plain text into ADF inline nodes.

        Args:
            text: Plain text. It is not interpreted as markup.

        Returns:
            Text and hard-break nodes.
        '''
        content: list[dict] = []
        for index, line in enumerate(text.split('\n')):
            if index:
                content.append({'type': 'hardBreak'})
            if line:
                content.append({'type': 'text', 'text': line})
        return content or [{'type': 'text', 'text': ''}]

    def validate_link(self, jira_issue_id: str, jira_link_id: str) -> bool:
        '''
        Validate if a Jira link exists on a Jira issue.

        Args:
            jira_issue_id: The ID of the Jira issue.
            jira_link_id: The ID of the Jira link.

        Returns:
            True if the Jira link exists and is valid, False otherwise.
        '''
        try:
            self.jira.get_issue_remote_link_by_id(jira_issue_id, jira_link_id)
            return True
        except requests.exceptions.HTTPError as e:
            if e.response.status_code != 404:
                raise

        return False

    def update_link(self, jira_issue_id: str, jira_link_id: str, url: str, title: str) -> None:
        '''
        Update a Jira link with new data.

        Args:
            jira_issue_id: The ID of the Jira issue.
            jira_link_id: The ID of the Jira link to update.
            url: The new URL for the link.
            title: The new title for the link.
        '''
        self.jira.update_issue_remote_link_by_id(
            jira_issue_id,
            jira_link_id,
            url,
            title,
        )
