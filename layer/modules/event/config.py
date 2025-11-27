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
Configuration module for event handling settings.

This module loads configuration from either a JSON file or environment variables,
providing fallback behavior for different deployment environments. The configuration
includes emoji reactions, Jira link icons, and feature-specific settings.
It also includes the name of the Slack app.

Configuration Keys:
    success_reaction: Emoji name for successful event processing (e.g., 'white_check_mark')
    error_reaction: Emoji name for failed event processing (e.g., 'x')
    icon_url: URL of the icon displayed in Jira remote links
    icon_title: Title text for the icon in Jira remote links
    sync_reaction: Emoji name that triggers message syncing to Jira (e.g., 'speech_balloon')
    app_name: Name of the Slack app

Loading Strategy:
    1. Attempts to load from config.json in the same directory
    2. Falls back to environment variables if JSON file fails
    3. Logs error if JSON loading fails but continues with env vars

Environment Variables (fallback):
    SUCCESS_REACTION: Success emoji name
    ERROR_REACTION: Error emoji name
    ICON_URL: Jira link icon URL
    ICON_TITLE: Jira link icon title
    SYNC_REACTION: Sync trigger emoji name
    APP_NAME: Name of the Slack app
Usage:
    >>> from event.config import CONFIG
    >>> success_emoji = CONFIG['success_reaction']
    >>> print(success_emoji)
    'white_check_mark'

Attributes:
    CONFIG_FILE: Path to the config.json file
    CONFIG: Dictionary containing all configuration values
'''

from pathlib import Path
import json
import logging
import os

# Path to configuration file in the same directory as this module
CONFIG_FILE = Path(Path(__file__).parent, 'config.json')
logger = logging.getLogger()

try:
    # Attempt to load configuration from JSON file
    with CONFIG_FILE.open(encoding='utf-8') as config_file:
        CONFIG = json.load(config_file)
except Exception as e:  # pylint: disable=bare-except
    # Fallback to environment variables if JSON file is missing or invalid
    logger.error(f'Error loading config file: {CONFIG_FILE}: {e}')
    CONFIG = {
        'success_reaction': os.getenv('SUCCESS_REACTION'),
        'error_reaction': os.getenv('ERROR_REACTION'),
        'icon_url': os.getenv('ICON_URL'),
        'icon_title': os.getenv('ICON_TITLE'),
        'sync_reaction': os.getenv('SYNC_REACTION'),
        'app_name': os.getenv('APP_NAME'),
    }
