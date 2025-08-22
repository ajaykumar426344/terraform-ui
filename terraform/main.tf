terraform {
  required_version = ">= 1.3.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region = var.region
  # Will use instance role via IMDS; no static creds.
}

# -------------------- Context Lookups --------------------
data "aws_vpc" "selected" {
  id = var.vpc_id
}

data "aws_subnet" "selected" {
  id = var.subnet_id
}

# -------------------- AMIs (latest) ---------------------
# Windows 2019
data "aws_ami" "windows2019" {
  most_recent = true
  owners      = ["801119661308"] # Amazon Windows
  filter {
    name   = "name"
    values = ["Windows_Server-2019-English-Full-Base-*"]
  }
  filter {
    name   = "state"
    values = ["available"]
  }
}

# Windows 2022
data "aws_ami" "windows2022" {
  most_recent = true
  owners      = ["801119661308"] # Amazon Windows
  filter {
    name   = "name"
    values = ["Windows_Server-2022-English-Full-Base-*"]
  }
  filter {
    name   = "state"
    values = ["available"]
  }
}

# Amazon Linux 2 (x86_64, gp2)
data "aws_ami" "al2" {
  most_recent = true
  owners      = ["137112412989"] # Amazon Linux AMI owner
  filter {
    name   = "name"
    values = ["amzn2-ami-hvm-*-x86_64-gp2"]
  }
  filter {
    name   = "state"
    values = ["available"]
  }
}

# -------------------- Security Groups -------------------
# SGs are selected by OS tag inside the chosen VPC; fallback to the
# VPC's default SG if none are found.

data "aws_security_groups" "windows" {
  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }
  filter {
    name   = "tag:OS"
    values = ["windows"]
  }
}

data "aws_security_groups" "linux" {
  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }
  filter {
    name   = "tag:OS"
    values = ["linux"]
  }
}

# The default SG of the selected VPC (always present)
data "aws_security_group" "default" {
  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }
  filter {
    name   = "group-name"
    values = ["default"]
  }
}

# -------------------- Locals ----------------------------
locals {
  # Determine target AMI (explicit -> by os_type)
  _ami_from_type = (
    var.os_type == "windows2019" ? data.aws_ami.windows2019.id :
    var.os_type == "windows2022" ? data.aws_ami.windows2022.id :
    data.aws_ami.al2.id
  )

  final_ami = var.ami_id != "" ? var.ami_id : local._ami_from_type

  is_windows = contains(["windows2019", "windows2022"], var.os_type)

  desired_sg_ids = local.is_windows ? data.aws_security_groups.windows.ids : data.aws_security_groups.linux.ids

  # Safe fallback to default SG if no tag-matched SGs found
  vpc_sg_ids = length(local.desired_sg_ids) > 0 ? local.desired_sg_ids : [data.aws_security_group.default.id]

  # Effective name: UI-provided or default
  effective_instance_name = coalesce(trimspace(var.instance_name), "dynamic-os-instance")

  # Linux cloud-init user-data to set hostname
  linux_user_data = <<-CLOUDINIT
    #cloud-config
    preserve_hostname: false
    hostname: ${local.effective_instance_name}
    fqdn: ${local.effective_instance_name}.local
  CLOUDINIT

  # Windows PowerShell user-data to set hostname (reboot once)
  windows_user_data = <<-POWERSHELL
    <powershell>
    try {
      Rename-Computer -NewName "${local.effective_instance_name}" -Force -Restart
    } catch {
      # If already named or another transient issue, write event and continue
      try {
        New-EventLog -LogName Application -Source "EC2UserData" -ErrorAction SilentlyContinue
      } catch {}
      Write-EventLog -LogName Application -Source "EC2UserData" -EntryType Warning -EventId 1000 -Message $_.Exception.Message
    }
    </powershell>
  POWERSHELL

  # Choose user_data based on OS
  chosen_user_data = var.os_type == "linux" ? local.linux_user_data : local.windows_user_data
}

# -------------------- EC2 Instance ----------------------
resource "aws_instance" "os_based_instance" {
  ami                         = local.final_ami
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  private_ip                  = var.private_ip
  associate_public_ip_address = false

  vpc_security_group_ids = local.vpc_sg_ids

  # Use null when no key to avoid empty-string issues
  key_name = var.key_name != "" ? var.key_name : null

  # Set hostname via user_data for both Linux and Windows
  user_data = local.chosen_user_data

  tags = {
    Name = local.effective_instance_name
    OS   = var.os_type
  }

  # Optional guard: don't recreate instance when an AMI's "latest" drifts
  lifecycle {
    ignore_changes = [
      ami
    ]
  }
}

