variable "region" {
  description = "AWS region"
  type        = string
}

variable "os_type" {
  description = "Operating system: windows2019 | windows2022 | linux"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.micro"
}

variable "vpc_id" {
  description = "Target VPC ID"
  type        = string
}

variable "subnet_id" {
  description = "Target Subnet ID (must belong to vpc_id)"
  type        = string
}

variable "private_ip" {
  description = "Static private IP to assign (must be within subnet CIDR)"
  type        = string
}

variable "key_name" {
  description = "EC2 key pair name. Leave empty for no key pair."
  type        = string
  default     = ""
}

variable "instance_name" {
  description = "Name tag and hostname. Leave empty to use a default."
  type        = string
  default     = ""
}

# Optional: support explicit AMI pinning from the UI
variable "ami_id" {
  description = "Optional explicit AMI ID (overrides os_type selection when non-empty)"
  type        = string
  default     = ""
}

