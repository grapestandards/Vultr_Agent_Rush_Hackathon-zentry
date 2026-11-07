output "public_ips" {
  value = { for k, vm in vultr_instance.vm : k => vm.main_ip }
}

output "private_ips" {
  value = { for k, vm in vultr_instance.vm : k => vm.internal_ip }
}

output "coolify_dashboard" {
  value = "http://${vultr_instance.vm["app"].main_ip}:8000"
}

output "vpc_id" {
  description = "VULTR_VPC_ID for the Training VM"
  value       = vultr_vpc.zentry.id
}
