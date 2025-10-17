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

resource "null_resource" "layer_requirements_install" {
  provisioner "local-exec" {
    command = <<EOT
podman run --rm --platform linux/arm64 -v ${path.module}:/app -w /app python:3.13 /app/layer_script.sh
EOT
  }

  triggers = {
    pyproject    = filesha256("${path.module}/pyproject.toml")
    lockfile     = filesha256("${path.module}/poetry.lock")
    layer_script = filesha256("${path.module}/layer_script.sh")
    python_modules = sha256(
      join(
        "",
        [
          for f in fileset("${path.module}/layer/modules", "**") :
          filesha256("${path.module}/layer/modules/${f}")
        ]
      )
    )
  }
}

resource "local_file" "config_file" {
  filename = "${path.module}/layer/python/event/config.json"
  content = jsonencode({
    hash             = sha256(join("", [for k, v in null_resource.layer_requirements_install.triggers : "${k}:${v}"])),
    success_reaction = var.tick_reaction,
    error_reaction   = var.x_reaction,
    icon_url         = var.icon_url,
    icon_title       = var.icon_title,
    sync_reaction    = var.sync_reaction,
    app_name         = var.app_name,
    tick_reaction    = var.tick_reaction,
    x_reaction       = var.x_reaction
  })

  depends_on = [null_resource.layer_requirements_install]
}

data "archive_file" "layer_archive" {
  type        = "zip"
  source_dir  = "layer"
  output_path = "layer.zip"

  excludes = [
    "modules/*",
  ]

  depends_on = [local_file.config_file]
}

resource "aws_lambda_layer_version" "layer" {
  layer_name               = "${local.project_name}_layer${local.suffix}"
  description              = "Layer for ${local.project_name} project"
  compatible_runtimes      = ["python3.13"]
  compatible_architectures = ["arm64"]

  source_code_hash = data.archive_file.layer_archive.output_base64sha256
  filename         = data.archive_file.layer_archive.output_path

  depends_on = [data.archive_file.layer_archive]
  lifecycle {
    create_before_destroy = true
  }
}