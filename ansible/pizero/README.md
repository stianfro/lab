# pizero

This playbook provisions the Raspberry Pi Zero at 192.168.1.193 as the
office call endpoint. It installs the yobidashi service from the sibling
repo checkout at `/home/stian/src/github.com/stianfro/yobidashi`.

## Prerequisites

- Your SSH key is installed on the Pi for the login user.
- The yobidashi repo is checked out at the path in
  `group_vars/pizeros.yaml` (`yobidashi_repo_path`).
- The MQTT password is exported in your shell:

  ```sh
  export YOBIDASHI_MQTT_PASSWORD=...
  ```

  The playbook fails early if this variable is empty. No secret is stored
  in this repo.

- Verify `yobidashi_mqtt_host` in `group_vars/pizeros.yaml`. It must match
  the mosquitto LoadBalancer IP from `apps/mosquitto`.

## Run

Run from the repo root:

```sh
YOBIDASHI_MQTT_PASSWORD=... \
  ansible-playbook -i ansible/pizero/inventory.ini ansible/pizero/playbook.yaml
```

The role is found next to the playbook (`ansible/pizero/roles/`), so the
`roles_path` in the repo `ansible.cfg` does not affect this playbook.

## Override the login user

The default login user is `stianfroystein`. To override it:

```sh
YOBIDASHI_MQTT_PASSWORD=... \
  ansible-playbook -i ansible/pizero/inventory.ini ansible/pizero/playbook.yaml \
  -e ansible_user=pi
```

You can also edit `ansible_user` in `inventory.ini`.

## Existing services

The Pi also runs an unrelated `sensor.service`. This playbook does not
touch it.

## Reboot note

The playbook enables I2C in the boot config. If it changed the file, it
prints a message. Reboot the Pi manually. The playbook does not reboot the
Pi.

## Verify

```sh
ssh <user>@192.168.1.193 systemctl status yobidashi
ssh <user>@192.168.1.193 journalctl -u yobidashi -f
```
