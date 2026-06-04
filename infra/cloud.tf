# TODO[P2]: выбрать провайдер (Yandex Cloud / AWS / GCP) перед защитой, ветка b12.
# Cloud deploy intentionally stays outside the default local Terraform path.
# The local provider plan must not require cloud credentials.
#
# Skeleton for b12:
#
# variable "cloud_region" {
#   type        = string
#   description = "Cloud region for the NBO VM deploy."
#   default     = ""
# }
#
# provider "[unknown]" {
#   # TODO[P2]: configure selected provider after the deploy target is chosen.
# }
#
# resource "[unknown]_instance" "nbo_vm" {
#   # TODO[P2]: one VM with docker compose runtime.
# }
#
# resource "[unknown]_security_group" "nbo_api" {
#   # TODO[P2]: expose only SSH from admin IP and API /health port.
# }
#
# resource "[unknown]_dns_record" "nbo_health" {
#   # TODO[P2]: optional public DNS record for the defense health URL.
# }
