"""
Collect inventory from vCenter via pyVmomi and write one RVTools-like .xlsx
(vInfo, vHost, vDisk sheets) for the existing analysis pipeline.
"""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from pyVim.connect import Disconnect, SmartConnect
    from pyVmomi import vim
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "vCenter import requires pyvmomi. Install: pip install pyvmomi"
    ) from e


def _walk_parents(obj: Any) -> tuple[str, str]:
    """Return (datacenter_name, cluster_or_host_group_name)."""
    dc_name = ""
    cluster_name = ""
    cur = obj
    while cur is not None:
        if isinstance(cur, vim.Datacenter):
            dc_name = cur.name
        elif isinstance(cur, vim.ClusterComputeResource):
            cluster_name = cur.name
        elif isinstance(cur, vim.ComputeResource) and not isinstance(
            cur, vim.ClusterComputeResource
        ):
            cluster_name = cur.name
        cur = getattr(cur, "parent", None)
    return dc_name, cluster_name or ""


def _nic_count(vm: vim.VirtualMachine) -> int:
    n = 0
    if not vm.config or not vm.config.hardware:
        return 0
    for dev in vm.config.hardware.device:
        if isinstance(dev, vim.vm.device.VirtualEthernetCard):
            n += 1
    return n


def _provisioned_mib(vm: vim.VirtualMachine) -> float:
    total_kb = 0
    if not vm.config or not vm.config.hardware:
        return 0.0
    for dev in vm.config.hardware.device:
        if isinstance(dev, vim.vm.device.VirtualDisk):
            total_kb += dev.capacityInKB or 0
    return total_kb / 1024.0


def _disk_rows(vm: vim.VirtualMachine) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not vm.config or not vm.config.hardware:
        return rows
    for dev in vm.config.hardware.device:
        if isinstance(dev, vim.vm.device.VirtualDisk):
            ctrl = "scsi"
            if dev.backing and "ide" in str(type(dev.backing)).lower():
                ctrl = "ide 0"
            elif isinstance(dev.controllerKey, int):
                ctrl = f"scsi controller {dev.controllerKey}"
            rows.append(
                {
                    "VM": vm.name,
                    "Controller": ctrl,
                }
            )
    return rows


def collect_to_xlsx(
    host: str,
    user: str,
    password: str,
    *,
    port: int = 443,
    disable_ssl_verify: bool = True,
    out_path: Path | None = None,
) -> Path:
    """
    Connect to vCenter and write RVTools-like workbook.
    """
    if out_path is None:
        out_path = Path.cwd() / "vcenter_inventory.xlsx"

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if disable_ssl_verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    si = SmartConnect(
        host=host,
        user=user,
        pwd=password,
        port=port,
        sslContext=ctx,
    )
    try:
        content = si.RetrieveContent()
        vinfo_rows: list[dict[str, Any]] = []
        vdisk_rows: list[dict[str, Any]] = []
        host_map: dict[str, dict[str, Any]] = {}

        # VMs
        view = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.VirtualMachine], True
        )
        try:
            for vm in view.view:
                if not isinstance(vm, vim.VirtualMachine):
                    continue
                if not vm.config:
                    continue
                dc, cluster = _walk_parents(vm)
                guest_os = ""
                if vm.guest and vm.guest.guestFullName:
                    guest_os = vm.guest.guestFullName
                elif vm.config and vm.config.guestFullName:
                    guest_os = vm.config.guestFullName
                cfg_os = ""
                if vm.config and vm.config.guestId:
                    cfg_os = vm.config.guestId

                conn = ""
                ps = ""
                if vm.runtime:
                    cs = vm.runtime.connectionState
                    conn = cs.name if hasattr(cs, "name") else str(cs)
                    pst = vm.runtime.powerState
                    ps = pst.name if hasattr(pst, "name") else str(pst)

                tpl = bool(vm.config and vm.config.template)

                vinfo_rows.append(
                    {
                        "VM": vm.name,
                        "OS according to the VMware Tools": guest_os,
                        "OS according to the configuration file": cfg_os,
                        "Template": tpl,
                        "SRM Placeholder": False,
                        "Connection state": conn,
                        "Powerstate": ps,
                        "Memory": float(vm.config.hardware.memoryMB)
                        if vm.config and vm.config.hardware
                        else 0.0,
                        "CPUs": float(vm.config.hardware.numCPU)
                        if vm.config and vm.config.hardware
                        else 0.0,
                        "NICs": float(_nic_count(vm)),
                        "Provisioned MiB": _provisioned_mib(vm),
                        "Datacenter": dc,
                        "Cluster": cluster,
                        "Environment": "",
                    }
                )
                vdisk_rows.extend(_disk_rows(vm))
        finally:
            view.Destroy()

        # Hosts
        hview = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.HostSystem], True
        )
        try:
            for hs in hview.view:
                if not isinstance(hs, vim.HostSystem):
                    continue
                hw = hs.hardware
                if not hw:
                    continue
                vendor = (
                    hw.systemInfo.vendor if hw.systemInfo else ""
                )
                model = hw.systemInfo.model if hw.systemInfo else ""
                mem_mb = (
                    float(hw.memorySize) / (1024.0 * 1024.0) if hw.memorySize else 0.0
                )
                cpu_total = 0
                cores = 0
                if hw.cpuInfo:
                    cores = int(hw.cpuInfo.numCpuCores or 0)
                    cpu_total = int(hw.cpuInfo.numCpuPackages or 0)
                host_map[hs.name] = {
                    "Host": hs.name,
                    "# VMs total": 0,
                    "# CPU": cpu_total,
                    "# Memory": mem_mb,
                    "# Cores": cores,
                    "Vendor": vendor,
                    "Model": model,
                }
        finally:
            hview.Destroy()

        # Count VMs per host
        vmview = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.VirtualMachine], True
        )
        try:
            for vm in vmview.view:
                if (
                    not isinstance(vm, vim.VirtualMachine)
                    or not vm.runtime
                    or not vm.runtime.host
                ):
                    continue
                hn = vm.runtime.host.name
                if hn in host_map:
                    host_map[hn]["# VMs total"] += 1
        finally:
            vmview.Destroy()

        vhost_rows = list(host_map.values())

        vinfo_df = pd.DataFrame(vinfo_rows)
        vhost_df = pd.DataFrame(vhost_rows)
        vdisk_df = pd.DataFrame(vdisk_rows) if vdisk_rows else pd.DataFrame(
            columns=["VM", "Controller"]
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(out_path, engine="openpyxl") as w:
            vinfo_df.to_excel(w, sheet_name="vInfo", index=False)
            vhost_df.to_excel(w, sheet_name="vHost", index=False)
            vdisk_df.to_excel(w, sheet_name="vDisk", index=False)

        return out_path
    finally:
        Disconnect(si)
