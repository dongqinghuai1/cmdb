"""SNMP 采集驱动（apps.cmdb）。

分层（只读、永不写设备）：
1. transport —— 纯 Python SNMPv2c GETNEXT 走查（stdlib，无第三方依赖，UDP）；
2. profiles  ——
   - 'if-mib'：标准 IF-MIB（1.3.6.1.2.1.2.2.1）接口发现/状态/错误 —— 跨厂商通用；
   - 'cisco_wlc_9800'：无线适配骨架。Catalyst 9800 的 AP 数据在私有 MIB
     （AIRESPACE-WIRELESS-MIB 1.3.6.1.4.1.9.9.429），各型号 OID 映射需真实
     snmpwalk 样本校准——**未校准前主动报 RequiresCalibration，不写假数据**；
   - 'mock'：内置样例，仅回归/演示（不触网）。
3. collect(device, profile, mock) —— 走查 → 解析 → 落 cmdb DeviceInterface(+Stat)，
   无线映射留 seam。周期执行见 cmdb.snmp_collect（beat 10 分钟）。
"""
import logging
import socket
import struct

logger = logging.getLogger(__name__)

# ---------- SNMPv2c BER 编解码（最小子集） ----------
_TAG_INT = 0x02
_TAG_OCTET = 0x04
_TAG_OID = 0x06
_TAG_NULL = 0x05
_TAG_SEQ = 0x30
_TAG_CTR = 0x41
_TAG_GAUGE = 0x42
_TAG_TICKS = 0x43
_TAG_IP = 0x40


def _len(n):
    if n < 0x80:
        return bytes([n])
    out = b""
    while n:
        out = bytes([n & 0xFF]) + out
        n >>= 8
    return bytes([0x80 | len(out)]) + out


def _tlv(tag, payload):
    return bytes([tag]) + _len(len(payload)) + payload


def _enc_int(v):
    if v < 0:
        v += 1 << 64
    b = v.to_bytes((v.bit_length() + 8) // 8 or 1, "big")
    if b[0] & 0x80:
        b = b"\x00" + b
    return b


def _enc_oid(oid):
    parts = [int(x) for x in oid.strip(".").split(".")]
    out = bytes([parts[0] * 40 + parts[1]])
    for p in parts[2:]:
        chunk = [p & 0x7F]
        p >>= 7
        while p:
            chunk.append(0x80 | (p & 0x7F))
            p >>= 7
        out += bytes(reversed(chunk))
    return out


def _dec_len(buf, i):
    n = buf[i]
    i += 1
    if not (n & 0x80):
        return n, i
    ln = 0
    for _ in range(n & 0x7F):
        ln = (ln << 8) | buf[i]
        i += 1
    return ln, i


def _dec_oid(raw):
    parts = []
    first = raw[0]
    parts.append(first // 40)
    parts.append(first % 40)
    acc = 0
    for b in raw[1:]:
        acc = (acc << 7) | (b & 0x7F)
        if not (b & 0x80):
            parts.append(acc)
            acc = 0
    return ".".join(map(str, parts))


def _parse_tlvs(buf):
    """迭代解码 buf 内多个 TLV，返回 [(tag, payload)]。"""
    out, i = [], 0
    while i < len(buf):
        tag = buf[i]
        ln, j = _dec_len(buf, i + 1)
        out.append((tag, buf[j:j + ln]))
        i = j + ln
    return out


def _decode_value(tag, payload):
    if tag == _TAG_INT:
        return int.from_bytes(payload, "big", signed=True)
    if tag in (_TAG_CTR, _TAG_GAUGE, _TAG_TICKS):
        return int.from_bytes(payload, "big")
    if tag == _TAG_OID:
        return _dec_oid(payload)
    if tag == _TAG_OCTET or tag == _TAG_IP:
        try:
            return payload.decode("utf-8", "replace")
        except Exception:
            return payload.hex()
    return None


def _build_getnext(req_id, community, oid):
    varbind = _tlv(_TAG_SEQ, _tlv(_TAG_OID, _enc_oid(oid)) + _tlv(_TAG_NULL, b""))
    pdu = (_tlv(_TAG_SEQ, _tlv(_TAG_INT, _enc_int(req_id))
                + _tlv(_TAG_INT, _enc_int(0)) + _tlv(_TAG_INT, _enc_int(0)) + varbind))
    return (_tlv(_TAG_SEQ, _tlv(_TAG_INT, _enc_int(1))
                 + _tlv(_TAG_OCTET, community.encode()) + pdu))


def _udp_send(sock, req, host, port, timeout):
    sock.settimeout(timeout)
    sock.sendto(req, (host, port))
    data, _ = sock.recvfrom(65535)
    return data


def snmpwalk(host, community, root_oid, port=161, timeout=1.5, max_rows=2000, reqid_seed=1):
    """SNMPv2c GETNEXT 走查 root_oid 子树；返回 [(oid, value)]。无依赖纯 stdlib。"""
    req_id = reqid_seed
    oid = root_oid
    out = []
    root = root_oid.rstrip(".") + "."
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        for _ in range(max_rows):
            req_id += 1
            req = _build_getnext(req_id, community, oid)
            try:
                resp = _udp_send(s, req, host, port, timeout)
            except OSError as e:
                raise ValueError(f"SNMP 超时/不可达 {host}:{port}: {e}") from e
            # Message = SEQ{ version:int, community:octet, PDU:SEQ{...} }（外层先拆一层）
            outer = _parse_tlvs(resp)
            if not outer:
                raise ValueError("空响应")
            inner = _parse_tlvs(outer[0][1])
            if len(inner) < 3 or inner[2][0] != _TAG_SEQ:
                raise ValueError("非 SNMP 响应报文")
            pdu_parts = _parse_tlvs(inner[2][1])           # reqid, err, erridx, varbindlist
            if len(pdu_parts) < 4:
                return out
            err_status = _decode_value(pdu_parts[1][0], pdu_parts[1][1]) or 0
            if err_status:
                return out                               # 表尾 / noSuchName
            varbindlist = pdu_parts[3]
            entries = _parse_tlvs(varbindlist[1])        # 可能多个 varbind
            if not entries:
                return out
            vb = _parse_tlvs(entries[0][1])              # 内层 SEQ{oid,value}
            if len(vb) < 2:
                return out
            next_oid = _decode_value(vb[0][0], vb[0][1])
            if not isinstance(next_oid, str) or not next_oid.startswith(root):
                return out
            out.append((next_oid, _decode_value(vb[1][0], vb[1][1])))
            oid = next_oid
    return out


# ---------- IF-MIB 语义 ----------
# 1.3.6.1.2.1.2.2.1.<col>.<idx>
IF_COLS = {
    "ifIndex": 1, "ifDescr": 2, "ifType": 3, "ifSpeed": 5, "ifPhysAddress": 6,
    "ifAdminStatus": 7, "ifOperStatus": 8, "ifInOctets": 10, "ifInErrors": 14,
    "ifOutOctets": 16, "ifOutErrors": 20,
}
IF_ROOT = "1.3.6.1.2.1.2.2.1"


def parse_if_mib(rows):
    """rows: [(oid,value)] → {idx: {col: value}}。"""
    out = {}
    for oid, val in rows:
        parts = oid.split(".")
        try:
            idx = int(parts[-1])
            col = int(parts[-2])
        except (ValueError, IndexError):
            continue
        name = next((k for k, v in IF_COLS.items() if v == col), None)
        if name is None:
            continue
        out.setdefault(idx, {})[name] = val
    return out


def _mock_if_rows(octets_step=0):
    base = "1.3.6.1.2.1.2.2.1"
    rows = []
    for idx, (descr, speed, oper) in enumerate([
            ("GigabitEthernet0/0/0", 1000000000, 1),
            ("TwentyFiveGigE1/0/1", 25000000000, 1),
            ("GigabitEthernet0/0/2", 1000000000, 2)], start=1):
        oct_in = 1_000_000_000 + idx * 1000 + octets_step
        oct_out = 500_000_000 + idx * 500 + octets_step
        rows += [(f"{base}.{IF_COLS['ifIndex']}.{idx}", idx),
                 (f"{base}.{IF_COLS['ifDescr']}.{idx}", descr),
                 (f"{base}.{IF_COLS['ifType']}.{idx}", 6),
                 (f"{base}.{IF_COLS['ifSpeed']}.{idx}", speed),
                 (f"{base}.{IF_COLS['ifAdminStatus']}.{idx}", 1),
                 (f"{base}.{IF_COLS['ifOperStatus']}.{idx}", oper),
                 (f"{base}.{IF_COLS['ifInOctets']}.{idx}", oct_in),
                 (f"{base}.{IF_COLS['ifOutOctets']}.{idx}", oct_out),
                 (f"{base}.{IF_COLS['ifInErrors']}.{idx}", idx * 7),
                 (f"{base}.{IF_COLS['ifOutErrors']}.{idx}", idx * 3)]
    return rows


# ---------- Cisco Catalyst 9800 无线适配（校准接缝） ----------
# Catalyst 9800 (IOS-XE) 无线对象位于 AIRESPACE-WIRELESS-MIB（1.3.6.1.4.1.9.9.429）。
# 具体表/列的 OID 需真实设备 snmpwalk 样本校准后填入本映射（KEY → OID）。
WLC9800_AP_OIDS = {
    "ap_name": None,        # 待校准：AP 名（OctetString）
    "ap_mac": None,         # 待校准
    "ap_model": None,       # 待校准
    "ap_ip": None,          # 待校准
    "ap_channel_24": None,  # 待校准
    "ap_channel_5": None,   # 待校准
    "ap_tx_power": None,    # 待校准
    "ap_clients": None,     # 待校准
}
WLC9800_MIB_ROOT = "1.3.6.1.4.1.9.9.429"


class RequiresCalibration(Exception):
    """无线 MIB 映射未校准：调用方应提供真实 snmpwalk 样本（见 HANDOVER §28）。"""


def collect_aps_9800(host, community, port=161):
    """Catalyst 9800 AP 明细采集：映射未校准前拒绝返回伪数据。"""
    missing = [k for k, v in WLC9800_AP_OIDS.items() if not v]
    raise RequiresCalibration(
        f"cisco_wlc_9800 无线 OID 映射待校准（缺 {len(missing)} 个: "
        f"{'/'.join(missing)}）。请提供: snmpwalk -v2c -c <ro> <wlc> "
        f"{WLC9800_MIB_ROOT} 的输出样本后补填 apps/cmdb/snmp.py::WLC9800_AP_OIDS")


# ---------- 落库 ----------
def upsert_interfaces(device, parsed):
    """parsed: {idx: {ifDescr..}} → cmdb DeviceInterface + DeviceInterfaceStat。
    计数器差值（两次采样）→ in/out bps 与错误速率；同时留存 octets/errors 快照。"""
    from django.utils import timezone
    from apps.cmdb.models import DeviceInterface, DeviceInterfaceStat
    created = updated = 0
    now = timezone.now()
    for idx, m in parsed.items():
        name = (m.get("ifDescr") or f"if{idx}")[:64]
        oper = {1: "up", 2: "down"}.get(m.get("ifOperStatus"), "")
        admin = {1: "up", 2: "down"}.get(m.get("ifAdminStatus"), "")
        iface, is_new = DeviceInterface.objects.get_or_create(
            device_id=device.pk, name=name,
            defaults={"if_index": idx, "oper_status": oper, "admin_status": admin,
                      "speed_bps": m.get("ifSpeed")})
        if is_new:
            created += 1
        else:
            changed = []
            if iface.oper_status != oper:
                iface.oper_status, changed = oper, changed + ["oper_status"]
            if iface.admin_status != admin:
                iface.admin_status, changed = admin, changed + ["admin_status"]
            if iface.speed_bps != m.get("ifSpeed") and m.get("ifSpeed"):
                iface.speed_bps, changed = m.get("ifSpeed"), changed + ["speed_bps"]
            if changed:
                iface.save(update_fields=changed + ["updated_at"])
            updated += 1
        stat, _ = DeviceInterfaceStat.objects.get_or_create(interface=iface)
        patch = {"sampled_at": now}
        if m.get("ifInOctets") is not None:
            new_in_oct = int(m["ifInOctets"])
            patch["in_octets_total"] = new_in_oct
            if stat.sampled_at and now > stat.sampled_at:
                elapsed = (now - stat.sampled_at).total_seconds()
                d = new_in_oct - stat.in_octets_total
                if elapsed > 0 and d >= 0:
                    patch["in_bps"] = int(d * 8 / elapsed)
        if m.get("ifOutOctets") is not None:
            new_out_oct = int(m["ifOutOctets"])
            patch["out_octets_total"] = new_out_oct
            if stat.sampled_at and now > stat.sampled_at:
                elapsed = (now - stat.sampled_at).total_seconds()
                d = new_out_oct - stat.out_octets_total
                if elapsed > 0 and d >= 0:
                    patch["out_bps"] = int(d * 8 / elapsed)
        if m.get("ifInErrors") is not None and int(m["ifInErrors"]) != stat.in_errors_total:
            patch["in_errors_total"] = int(m["ifInErrors"])
        if m.get("ifOutErrors") is not None and int(m["ifOutErrors"]) != stat.out_errors_total:
            patch["out_errors_total"] = int(m["ifOutErrors"])
        if patch:
            DeviceInterfaceStat.objects.filter(pk=stat.pk).update(**patch)
    # 读回最新速率（供调用方/回归断言）
    rates = list(DeviceInterfaceStat.objects.filter(interface__device_id=device.pk)
                 .select_related("interface")
                 .values("interface__name", "in_bps", "out_bps", "in_octets_total")
                 .order_by("interface__if_index"))
    return {"created": created, "updated": updated, "interfaces": len(parsed),
            "rates": rates}


def collect(device, profile="if-mib", mock=False, port=161, community="public",
            octets_step=0):
    """对单台设备执行采集。mock=True 走内置样例（回归/演示，不触网；octets_step
    用于制造两次采样计数器增量以验证速率计算）。cisco_wlc_9800 无线部分未校准前抛
    RequiresCalibration（由调用方记录）。"""
    if mock:
        rows = _mock_if_rows(int(octets_step or 0))
    else:
        rows = snmpwalk(device.manage_ip or device.name, community,
                        IF_ROOT, port=port)
    parsed = parse_if_mib(rows)
    res = upsert_interfaces(device, parsed)
    wireless = {"aps": 0, "note": "非无线 profile/无样本"}
    if getattr(device, "driver_type", "") == "cisco_wlc_9800" and not mock:
        try:
            collect_aps_9800(device.manage_ip, community, port)
        except RequiresCalibration as e:
            wireless = {"aps": 0, "note": str(e)}
    return {"profile": profile, "mock": mock, **res, "wireless": wireless}


# ---------- LLDP-MIB（IEEE 802.1AB-2005）语义 ----------
# lldpMIB = 1.0.8802.1.1.2；lldpObjects 下 lldpConfiguration=1 / lldpStatistics=2 /
# lldpLocalSystemData=3 / lldpRemoteSystemsData=4。
#   lldpLocPortTable（本地端口号 → 描述，索引=portNum）: ...1.3.1.1.<col>.<portNum>
#   lldpRemTable（远端邻居，索引=timeMark.localPortNum.remIndex）: ...1.4.1.1.<col>.<t>.<p>.<r>
# 仅取"只读、只发现、不写设备"；落库与比对在 apps/topo（LldpNeighbor）+ dcim（Cable）。
LLDP_LOC_ENTRY = "1.0.8802.1.1.2.1.3.1.1"
LLDP_REM_ENTRY = "1.0.8802.1.1.2.1.4.1.1"
# entry 内列号 → 语义（本驱动消费子集；列 1-3 为索引/TimeFilter 不可访问）
LLDP_LOC_COLS = {"port_id_subtype": 2, "port_id": 3, "port_desc": 4}
LLDP_REM_COLS = {"chassis_id_subtype": 4, "chassis_id": 5,
                 "port_id_subtype": 6, "port_id": 7, "port_desc": 8,
                 "sys_name": 9, "sys_desc": 10}


def _parse_entry_rows(rows, entry_prefix, col_map, n_idx):
    """通用表解析：OID = <entry>.<col>.<idx...> → {(idx_tuple): {col: value}}。"""
    prefix = entry_prefix + "."
    rev = {v: k for k, v in col_map.items()}
    out = {}
    for oid, val in rows:
        if not oid.startswith(prefix):
            continue
        rest = oid[len(prefix):].split(".")
        try:
            col, idx = int(rest[0]), tuple(int(x) for x in rest[1:])
        except (ValueError, IndexError):
            continue
        name = rev.get(col)
        if name is None or len(idx) < n_idx:
            continue
        out.setdefault(idx, {})[name] = val
    return out


def parse_lldp_loc(rows):
    """lldpLocPortTable rows → {port_num: {port_id_subtype/port_id/port_desc}}。"""
    raw = _parse_entry_rows(rows, LLDP_LOC_ENTRY, LLDP_LOC_COLS, 1)
    return {idx[0]: m for idx, m in raw.items()}


def parse_lldp_rem(rows):
    """lldpRemTable rows → {(local_port, rem_index): {chassis_id_subtype/chassis_id/...}}。
    同 (port, rem) 的不同 timeMark 行合并（取后到者）。"""
    raw = _parse_entry_rows(rows, LLDP_REM_ENTRY, LLDP_REM_COLS, 3)
    out = {}
    for idx, m in raw.items():
        out.setdefault((idx[1], idx[2]), {}).update(m)
    return out


def collect_lldp(host, community, port=161, timeout=1.5):
    """LLDP 邻居走查（只读探针）：lldpLocPortTable + lldpRemTable → 解析结果。
    无 LLDP 使能的设备返回空表（不报错）。调用方负责凭据与目标范围。"""
    loc_rows = snmpwalk(host, community, LLDP_LOC_ENTRY, port=port, timeout=timeout)
    rem_rows = snmpwalk(host, community, LLDP_REM_ENTRY, port=port, timeout=timeout)
    return {"local": parse_lldp_loc(loc_rows), "remote": parse_lldp_rem(rem_rows)}
