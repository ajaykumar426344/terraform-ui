output "ami_used" {
  value = aws_instance.os_based_instance.ami
}

output "instance_id" {
  value = aws_instance.os_based_instance.id
}

output "os_type" {
  value = var.os_type
}

output "private_ip" {
  value = aws_instance.os_based_instance.private_ip
}

output "subnet_id" {
  value = var.subnet_id
}

output "vpc_security_group_ids" {
  value = aws_instance.os_based_instance.vpc_security_group_ids
}

output "instance_name" {
  value = local.effective_instance_name
}
output "region" {
  value = var.region
}

