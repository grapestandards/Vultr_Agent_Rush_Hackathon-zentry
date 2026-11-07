variable "region" {
  description = "Vultr region for everything (Singapore)"
  type        = string
  default     = "sgp"
}

variable "ssh_public_key" {
  description = "Public key installed on every VM (Coolify on the App VM also uses it to reach the others)"
  type        = string
}

variable "admin_cidr" {
  description = "Your IP range for SSH and the Coolify dashboard, e.g. 203.0.113.7/32"
  type        = string
}

variable "app_plan" {
  type    = string
  default = "vc2-2c-4gb"
}

variable "worker_plan" {
  type    = string
  default = "vc2-2c-4gb"
}

variable "data_plan" {
  type    = string
  default = "vc2-4c-8gb"
}
