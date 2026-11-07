# Zentry on Vultr: App (Coolify + web + API), Worker (detection, agents) and Data (Supabase + NATS)
# in one private VPC. Only the App VM is public, on 80/443. The on-demand Training VM is created by
# the API through the Vultr API at train time (M5), not here.

data "vultr_os" "ubuntu" {
  filter {
    name   = "name"
    values = ["Ubuntu 24.04 LTS x64"]
  }
}

resource "vultr_vpc" "zentry" {
  region         = var.region
  description    = "zentry"
  v4_subnet      = "10.20.0.0"
  v4_subnet_mask = 24
}

resource "vultr_ssh_key" "deploy" {
  name    = "zentry-deploy"
  ssh_key = var.ssh_public_key
}

# --- firewalls -----------------------------------------------------------------------------------
resource "vultr_firewall_group" "public" {
  description = "zentry-app: web traffic + admin"
}

resource "vultr_firewall_rule" "http" {
  firewall_group_id = vultr_firewall_group.public.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
  port              = "80"
  notes             = "http (redirects to https)"
}

resource "vultr_firewall_rule" "https" {
  firewall_group_id = vultr_firewall_group.public.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
  port              = "443"
  notes             = "https"
}

resource "vultr_firewall_group" "private" {
  description = "zentry-internal: admin ssh only (VPC traffic is not filtered)"
}

locals {
  admin_ip   = split("/", var.admin_cidr)[0]
  admin_mask = tonumber(split("/", var.admin_cidr)[1])
  admin_rules = {
    public_ssh     = { group = vultr_firewall_group.public.id, port = "22" }
    public_coolify = { group = vultr_firewall_group.public.id, port = "8000" }
    private_ssh    = { group = vultr_firewall_group.private.id, port = "22" }
  }
}

resource "vultr_firewall_rule" "admin" {
  for_each          = local.admin_rules
  firewall_group_id = each.value.group
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = local.admin_ip
  subnet_size       = local.admin_mask
  port              = each.value.port
  notes             = "admin ${each.key}"
}

# --- instances -----------------------------------------------------------------------------------
locals {
  vms = {
    app    = { plan = var.app_plan, firewall = vultr_firewall_group.public.id, cloud_init = "app.yaml" }
    worker = { plan = var.worker_plan, firewall = vultr_firewall_group.private.id, cloud_init = "node.yaml" }
    data   = { plan = var.data_plan, firewall = vultr_firewall_group.private.id, cloud_init = "node.yaml" }
  }
}

resource "vultr_instance" "vm" {
  for_each          = local.vms
  label             = "zentry-${each.key}"
  hostname          = "zentry-${each.key}"
  region            = var.region
  plan              = each.value.plan
  os_id             = data.vultr_os.ubuntu.id
  vpc_ids           = [vultr_vpc.zentry.id]
  firewall_group_id = each.value.firewall
  ssh_key_ids       = [vultr_ssh_key.deploy.id]
  user_data         = file("${path.module}/cloud-init/${each.value.cloud_init}")
  backups           = "disabled"
  enable_ipv6       = false
  tags              = ["zentry", "zentry-${each.key}"]
}
