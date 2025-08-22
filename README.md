Terraform UI 🌐

Terraform UI is a lightweight web-based interface built with Flask and Terraform to simplify infrastructure provisioning.
Instead of using the Terraform CLI directly, users can create, apply, and destroy AWS infrastructure through an intuitive UI.

✨ Features

🔄 Dynamic AWS Lookups
Fetch AWS resources (Regions, VPCs, Subnets, CIDR ranges) dynamically using boto3.

🖥️ Instance Configuration
Select Instance type, OS type, Private IP, and Region easily.

⚡ Terraform Integration

Auto-generates terraform.tfvars from UI input

Runs terraform plan & terraform apply

Supports destroy with one click

📊 Status Page
Monitor real-time progress and logs of infrastructure deployments.

🐳 Dockerized Runtime

Plugin cache enabled to fix provider exec/noexec issues

Environment isolated for consistency

🔒 IAM Role Support
Uses instance roles for secure AWS API calls.

🏗️ Architecture

Frontend / UI → HTML + Flask (Python)

Backend → Terraform CLI execution

Dynamic Data → AWS SDK (boto3)

Containerized → Docker & Docker Compose

🚀 Getting Started
Prerequisites

Docker & Docker Compose installed

AWS IAM Role or Credentials with appropriate permissions (EC2, VPC, Subnets)

Clone & Build

git clone https://github.com/ajaykumar426344/terraform-ui.git

cd terraform-ui

docker compose up --build -d

Access the App

Open: http://localhost:8080

⚙️ Configuration
Environment Variable	Description
TF_DATA_DIR	Path for Terraform working directory (default: /home/app/.terraformdata)
TF_PLUGIN_CACHE_DIR	Cache path for Terraform providers (default: /home/app/.terraform.d/plugin-cache)
AWS_REGION	Default AWS region if not selected in UI

📸 Screenshots
Provision Screen

Status Page (Apply)

Destroy Workflow

📌 Roadmap

 Add support for Azure / GCP

 Add Authentication (RBAC)

 Multi-environment support (dev, stage, prod)

 Audit logs

🤝 Contributing

Pull requests are welcome!
For major changes, please open an issue first to discuss what you’d like to change.

📜 License

MIT © 2025 Ajay kumar Abhisheety
