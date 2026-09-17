#!/bin/bash

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

set -euo pipefail

rm -rf /app/layer/python
mkdir -p /app/layer/python
cp -r /app/layer/modules/* /app/layer/python/
pip install poetry==2.2.1 poetry-plugin-export==1.9.0 python-inspector==0.14.3
poetry export -f requirements.txt --without-hashes --only main > requirements.txt
pip install --no-deps --target=/app/layer/python -r requirements.txt
rm requirements.txt

# A layer without the project modules deploys fine but fails at import time.
for module in /app/layer/modules/*; do
  target="/app/layer/python/$(basename "${module}")"
  if [ ! -e "${target}" ]; then
    echo "Layer build incomplete: ${target} is missing" >&2
    exit 1
  fi
done
