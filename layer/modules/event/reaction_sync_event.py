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
Reaction sync event module for syncing Slack messages to Jira comments.

This module provides the ReactionSyncEvent class that handles specific emoji
reactions (configured sync reaction) by copying the reacted message content
and attachments to linked Jira issues as comments.
'''

from __future__ import annotations

import asyncio
from datetime import datetime, UTC
import logging
from pathlib import Path
from typing import Any, Optional, cast, AsyncGenerator, List

import aiohttp
from tenacity import (
    retry,
    stop_after_attempt,
    wait_fixed,
    retry_if_exception_type,
    before_sleep_log,
    after_log,
)

from .reaction_event import ReactionEvent
from .event_factory import EventFactory
from .exceptions import IgnorableException
from .config import CONFIG

logger = logging.getLogger()


# TODO disassemble this class.
# TODO 429 retry handling.
class AsyncSlackToJiraTransfer:
    '''
    Asynchronous file transfer handler for streaming Slack files to multiple Jira issues.

    This class implements a producer-consumer pattern using asyncio queues to efficiently
    stream file downloads from Slack and fan them out to multiple concurrent Jira uploads.
    Files are downloaded once and uploaded to multiple Jira issues simultaneously, with
    chunked streaming to minimize memory usage.

    Architecture:
        - Producer: Downloads file from Slack in chunks (256 KiB)
        - Queues: One per Jira issue for buffering chunks
        - Consumers: Concurrent upload tasks reading from queues

    Attributes:
        IMAGE_EXTENSIONS: Tuple of image file extensions for Jira thumbnail rendering.
        CHUNK_SIZE_BYTES: Size of chunks for streaming (256 KiB).
        QUEUE_PUT_TIMEOUT_SECONDS: Timeout for putting chunks into queues (5s).
        QUEUE_MAXSIZE: Maximum number of chunks buffered per queue (4).
        GET_TIMEOUT_SECONDS: Timeout for Slack download connection (10s).
        UPLOAD_TIMEOUT_SECONDS: Timeout for entire Jira upload operation (100s).
    '''

    IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif')

    CHUNK_SIZE_BYTES = 256 * 1024
    QUEUE_PUT_TIMEOUT_SECONDS = 5
    QUEUE_MAXSIZE = 4
    GET_TIMEOUT_SECONDS = 10
    UPLOAD_TIMEOUT_SECONDS = 100

    def __init__(
        self,
        slack_token: str,
        jira_token: str,
        jira_server_url: str,
        channel_id: str,
        message_ts: str,
    ):
        '''
        Initialize the async transfer handler with authentication and metadata.

        Args:
            slack_token: Bearer token for Slack API authentication.
            jira_token: Bearer token for Jira API authentication.
            jira_server_url: Base URL of the Jira server (e.g., 'https://jira.example.com').
            channel_id: Slack channel ID for filename uniqueness.
            message_ts: Slack message timestamp for filename uniqueness.
        '''
        self.slack_token = slack_token
        self.jira_token = jira_token
        self.jira_api_url_template = f'{jira_server_url}/rest/api/2/issue/{{issue_id}}/attachments'
        self.channel_id = channel_id
        self.message_ts = message_ts

        now = datetime.now(UTC)

        # Note the time at creation of object for filename uniqueness
        self.formatted_ts = f'{now.strftime('%Y%m%d-%H%M%S')}{int(now.microsecond/1000):03d}'
        self.filename_suffix = f'{self.channel_id}-{self.message_ts}-{self.formatted_ts}'

    @staticmethod
    def filename_to_jira_markup(filename: str) -> str:
        '''
        Convert a filename to Jira markup for attachments.

        Generates appropriate Jira markup based on file type. Image files are
        rendered as inline thumbnails, while other files are shown as attachment links.

        Args:
            filename: The name of the attached file.

        Returns:
            Jira markup string: '!filename|thumbnail!' for images,
            '[^filename]' for other files.

        Example:
            'photo.png' -> '!photo.png|thumbnail!'
            'document.pdf' -> '[^document.pdf]'
        '''
        if filename.endswith(AsyncSlackToJiraTransfer.IMAGE_EXTENSIONS):
            return f'!{filename}|thumbnail!'

        return f'[^{filename}]'

    @staticmethod
    async def chunk_reader(queue: asyncio.Queue[bytes | None]) -> AsyncGenerator[bytes, None]:
        '''
        Async generator that reads chunks from a queue for streaming uploads.

        Continuously reads data chunks from the queue and yields them for consumption
        by the HTTP upload stream. Terminates when a None sentinel value is received.

        Args:
            queue: asyncio.Queue containing byte chunks and a None sentinel.

        Yields:
            bytes: Individual file chunks for streaming upload.

        Note:
            This generator is used by aiohttp.FormData to stream file data directly
            from the download queue to the upload request without buffering.
        '''
        while True:
            chunk = await queue.get()

            if chunk is None:
                break

            yield chunk

    async def process_jira_upload(
        self,
        session: aiohttp.ClientSession,
        queue: asyncio.Queue[bytes | None],
        jira_issue_id: str,
        filename: str,
        file_id: int,
    ) -> str:
        '''
        Upload a file to a Jira issue by streaming chunks from a queue.

        This is the consumer task that reads file chunks from a queue and streams
        them directly to Jira via HTTP multipart upload. The file is given a unique
        name to prevent collisions.

        Args:
            session: aiohttp.ClientSession for making HTTP requests.
            queue: asyncio.Queue containing file chunks to upload.
            jira_issue_id: The Jira issue ID to attach the file to.
            filename: Original filename from Slack.
            file_id: Sequential file index for uniqueness.

        Returns:
            str: Jira markup for the uploaded file (thumbnail or attachment link).

        Raises:
            Exception: If upload fails or times out after UPLOAD_TIMEOUT_SECONDS.

        Note:
            The upload streams directly from the queue without buffering the entire
            file, making it memory-efficient for large files.
        '''
        headers = {
            'Authorization': f'Bearer {self.jira_token}',
            'X-Atlassian-Token': 'no-check',
        }

        filename_path = Path(filename)
        new_filename = (
            f'{filename_path.name}-{file_id}-{self.filename_suffix}{filename_path.suffix}'
        )
        endpoint_url = self.jira_api_url_template.format(issue_id=jira_issue_id)

        form = aiohttp.FormData()
        form.add_field('file', self.chunk_reader(queue), filename=new_filename)

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_fixed(1),
            retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            after=after_log(logger, logging.ERROR),
            reraise=True,
        )
        async def do_post() -> None:
            async with session.post(endpoint_url, headers=headers, data=form) as resp:
                resp.raise_for_status()
                await resp.read()
                logger.info(f'Uploaded {filename} to jira issue {jira_issue_id}')

        post_task = asyncio.create_task(do_post())

        try:
            await asyncio.wait_for(post_task, timeout=self.UPLOAD_TIMEOUT_SECONDS)
        except Exception as e:
            post_task.cancel()
            await asyncio.gather(post_task, return_exceptions=True)

            logger.error(f'Upload failed for {filename} -> {new_filename} to {endpoint_url}: {e}')
            raise

        return self.filename_to_jira_markup(new_filename)

    async def download_and_process_file(
        self,
        session: aiohttp.ClientSession,
        file: dict[str, str],
        jira_issue_ids: list[str],
        file_id: int,
    ) -> List[str]:
        '''
        Download a file from Slack and concurrently upload to multiple Jira issues.

        Implements the producer-consumer pattern:
        1. Creates one queue per Jira issue
        2. Starts upload tasks (consumers) for each queue
        3. Downloads file in chunks and distributes to all queues (producer)
        4. Monitors upload task states and stops sending to failed uploads
        5. Sends sentinel values to close streams gracefully

        Args:
            session: aiohttp.ClientSession for HTTP requests.
            file: Dict with 'name' and 'url' keys from Slack API.
            jira_issue_ids: List of Jira issue IDs to upload the file to.
            file_id: Sequential file index for unique naming.

        Returns:
            List[str]: Jira markup for each issue (empty string if upload failed).

        Note:
            The file is downloaded once and streamed to multiple uploads concurrently,
            significantly reducing memory usage compared to downloading N times.
        '''
        # pylint: disable=too-many-locals

        filename, url = file['name'], file['url']
        slack_headers = {
            'Authorization': f'Bearer {self.slack_token}',
        }

        queues: List[asyncio.Queue[bytes | None]] = [
            asyncio.Queue(maxsize=self.QUEUE_MAXSIZE) for _ in jira_issue_ids
        ]

        upload_tasks = [
            asyncio.create_task(
                self.process_jira_upload(
                    session,
                    queue,
                    jira_issue_id,
                    filename,
                    file_id,
                ),
            )
            for jira_issue_id, queue in zip(jira_issue_ids, queues)
        ]

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_fixed(1),
            retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        async def get_response() -> aiohttp.ClientResponse:
            resp = await session.get(
                url,
                headers=slack_headers,
                timeout=aiohttp.ClientTimeout(total=self.GET_TIMEOUT_SECONDS),
            )
            resp.raise_for_status()
            return resp

        try:
            async with await get_response() as resp:
                async for chunk in resp.content.iter_chunked(self.CHUNK_SIZE_BYTES):
                    results = await asyncio.gather(
                        *[
                            (
                                asyncio.wait_for(
                                    queue.put(chunk),
                                    timeout=self.QUEUE_PUT_TIMEOUT_SECONDS,
                                )
                                if queue is not None and not upload_task.done()
                                else asyncio.sleep(0)
                            )
                            for upload_task, queue in zip(upload_tasks, queues)
                        ],
                        return_exceptions=True,
                    )

                    for idx, (jira_issue_id, result) in enumerate(zip(jira_issue_ids, results)):
                        if isinstance(result, Exception):
                            logger.error(
                                f'Failed to send chunk of file {filename} to Jira issue '
                                f'{jira_issue_id}: {result}. Will mark this upload as failure.'
                            )
                            queues[idx].shutdown(immediate=True)
                            queues[idx] = None  # type: ignore
                            upload_tasks[idx].cancel()

        except Exception as e:
            logger.error(f'Failed to download file {file_id}: {filename}: {e}')

            for upload_task in upload_tasks:
                upload_task.cancel()

        finally:
            await asyncio.gather(
                *[
                    asyncio.wait_for(queue.put(None), timeout=self.QUEUE_PUT_TIMEOUT_SECONDS)
                    for queue in queues
                    if queue
                ],
                return_exceptions=True,
            )

        upload_task_results: List[Any] = await asyncio.gather(*upload_tasks, return_exceptions=True)

        return [
            result if not isinstance(result, (Exception, type(None))) else ''
            for result in upload_task_results
        ]

    async def transfer(
        self, file_urls: List[dict[str, str]], jira_issue_ids: List[str]
    ) -> List[List[str]]:
        '''
        Transfer multiple files from Slack to multiple Jira issues concurrently.

        Orchestrates the entire transfer process:
        1. Creates one download task per file
        2. Each download fans out to N Jira uploads
        3. All operations run concurrently
        4. Returns markup results grouped by file

        Args:
            file_urls: List of file dicts with 'url' and 'name' keys from Slack.
            jira_issue_ids: List of Jira issue IDs to upload files to.

        Returns:
            List[List[str]]: Outer list = files, inner list = Jira markup per issue.
            Returns empty strings for failed uploads.

        Example:
            For 2 files and 3 Jira issues:
            [
                ['!file1.png|thumbnail!', '!file1.png|thumbnail!', '!file1.png|thumbnail!'],
                ['[^file2.pdf]', '[^file2.pdf]', '[^file2.pdf]']
            ]

        Note:
            The return structure is transposed by the caller to group by Jira issue.
        '''
        async with aiohttp.ClientSession() as session:
            file_tasks = [
                asyncio.create_task(
                    self.download_and_process_file(session, file, jira_issue_ids, file_id)
                )
                for file_id, file in enumerate(file_urls)
            ]
            file_task_results: List[Any] = await asyncio.gather(*file_tasks, return_exceptions=True)
            return [
                (
                    file_task_result
                    if not isinstance(file_task_result, (Exception, type(None)))
                    else ['' for _ in jira_issue_ids]
                )
                for file_task_result in file_task_results
            ]


class ReactionSyncEvent(ReactionEvent):
    '''
    Event handler for syncing Slack messages to Jira via reaction.

    This event is triggered when users add a specific emoji reaction (e.g., 💬)
    to a message in a thread that's registered to one or more Jira issues.

    The workflow:
    1. User adds sync reaction to a message in a registered thread
    2. Bot retrieves the message content and file attachments
    3. Bot looks up all Jira issues linked to this thread
    4. Bot posts message as comment to each linked Jira issue
    5. Bot downloads and attaches files to each Jira issue

    File attachments are given unique names to prevent collisions and include
    metadata (channel, timestamp, sequence) for traceability.

    Attributes:
        name: The emoji name for sync reaction (from CONFIG).
    '''

    name: str = CONFIG['sync_reaction']

    def _handle_event_sub_type(self, args: Any) -> None:
        '''
        Handle event subtype (no-op for reaction sync).

        Reaction sync events don't have additional arguments to process.
        The reaction emoji itself is sufficient to identify the action.

        Args:
            args: Always None for reaction events.
        '''

    def _process_event(self) -> None:
        '''
        Sync a Slack message and its attachments to linked Jira issues.

        This method implements the core comment syncing logic:
        1. Get the thread_ts for the reacted message
        2. Query DynamoDB for all Jira issues linked to this thread
        3. Retrieve message content and file URLs from Slack
        4. Process and upload file attachments to each Jira issue
        5. Format message text with Slack link attribution
        6. Post formatted text and attachment markup as comment to each Jira issue

        The method handles multiple Jira issues linked to the same thread,
        copying the comment and attachments to all of them.

        Raises:
            IgnorableException: If the thread is not registered to any Jira issues.
        '''
        thread_ts: Optional[str] = self.slack_sdk_wrapper.get_thread_ts_from_message_ts(
            self.channel_id, self.message_ts  # type: ignore
        )
        if thread_ts is None:
            raise IgnorableException(
                f'No thread_ts found for message {self.message_ts} in channel {self.channel_id}'
            )

        if self.dynamo_db_wrapper is None:
            raise IgnorableException(
                f'No dynamo_db_wrapper found for message {self.message_ts} '
                f'in channel {self.channel_id}'
            )

        if self.jira_wrapper is None:
            raise IgnorableException(
                f'No jira_wrapper found for message {self.message_ts} '
                f'in channel {self.channel_id}'
            )

        items = self.dynamo_db_wrapper.query(
            'slack_thread_id', self._get_thread_id(thread_ts, self.channel_id)  # type: ignore
        )
        if not items:
            raise IgnorableException(
                f'No items found for thread {self._get_thread_id(thread_ts, self.channel_id)}, '  # type: ignore # pylint: disable=line-too-long
                'skipping comment.'
            )

        text, files = self.slack_sdk_wrapper.get_content_from_message_ts(
            self.channel_id, self.message_ts  # type: ignore
        )
        message_link = self.slack_sdk_wrapper.get_message_link(self.channel_id, self.message_ts)  # type: ignore # pylint: disable=line-too-long

        jira_issue_ids: list[str] = [cast(str, item.get('jira_issue_id')) for item in items]

        attachment_contents = []
        if files:
            attachment_contents = self.process_file_attachments(
                files, jira_issue_ids, self.channel_id, self.message_ts  # type: ignore
            )

        formatted_text = self._format_text(text, message_link)  # type: ignore

        for idx, jira_issue_id in enumerate(jira_issue_ids):
            self.jira_wrapper.add_comment(
                jira_issue_id,
                f'{formatted_text}\n\n{attachment_contents[idx] if attachment_contents else ''}',
            )

    @staticmethod
    def _format_text(text: str, message_link: str) -> str:
        '''
        Format text with a Slack message link reference for Jira.

        Prepends attribution link to the original Slack message using Jira's
        markdown-style link syntax. This provides traceability from Jira
        comments back to their source Slack messages.

        Args:
            text: The original message text from Slack.
            message_link: The Slack permalink to the message.

        Returns:
            The formatted text with attribution in Jira markdown format.

        Example:
            "(Originating from [Slack message|https://...slack.com/...])\n\nActual message text"
        '''
        return f'(Originating from [Slack message|{message_link}])\n\n{text}'

    def process_file_attachments(
        self,
        file_urls: list[dict[str, str]],
        jira_issue_ids: list[str],
        channel_id: str,
        message_ts: str,
    ) -> list[str]:
        '''
        Process Slack file attachments and upload to multiple Jira issues with streaming.

        This method orchestrates the async file transfer process, delegating to
        AsyncSlackToJiraTransfer for efficient streaming downloads and concurrent
        uploads. Files are downloaded once from Slack and streamed to multiple Jira
        issues simultaneously using a producer-consumer pattern with asyncio queues.

        Each file receives a unique name to prevent collisions and enable traceability.
        Image files are rendered as inline thumbnails in Jira comments, while other
        files are shown as attachment links.

        Args:
            file_urls: List of file dictionaries with 'url' and 'name' keys from Slack.
            jira_issue_ids: List of Jira issue IDs to attach files to.
            channel_id: Slack channel ID used in unique filename generation.
            message_ts: Slack message timestamp used in unique filename generation.

        Returns:
            List[str]: One string per Jira issue containing newline-separated Jira
            markup for all successfully uploaded files. Failed uploads are omitted.

        Example:
            For 2 files uploaded to 3 Jira issues:
            [
                '!photo.png|thumbnail!\n\n[^document.pdf]',  # Issue 1
                '!photo.png|thumbnail!\n\n[^document.pdf]',  # Issue 2
                '!photo.png|thumbnail!\n\n[^document.pdf]',  # Issue 3
            ]

        Filename Format:
            {original_name}-{file_index}-{channel_id}-{message_ts}-{timestamp}.{ext}
            Example: 'report.pdf-0-C1234567890-1234567890123456-20240107-153045123.pdf'

        Note:
            This is a synchronous wrapper around async transfer operations. It uses
            asyncio.run() to execute the streaming downloads and concurrent uploads,
            then transposes the results from [file][issue] to [issue][file] format.
        '''
        message_ts = message_ts.replace('.', '')

        async_slack_to_jira_transfer = AsyncSlackToJiraTransfer(
            self.slack_sdk_wrapper.client.token,  # type: ignore
            self.jira_wrapper.jira_token,  # type: ignore
            self.jira_wrapper.server_url,  # type: ignore
            channel_id,
            message_ts,
        )
        jira_markups: List[List[str]] = asyncio.run(
            async_slack_to_jira_transfer.transfer(file_urls, jira_issue_ids)
        )

        return ['\n\n'.join(jira_markup) for jira_markup in zip(*jira_markups)]


# Register this concrete event type with the factory for reaction routing
EventFactory.concrete_event_types[ReactionSyncEvent.name] = ReactionSyncEvent
