"""CMDB 技术快照采集解析器（collectors）：把设备 CLI 输出文本解析为结构化 payload，
供 POST /cmdb/devices/{id}/tech-parse/ 预览/落库（写 TechSnapshot: acl/nat/ipsec）。

各解析器均为"纯函数 + 贴文本"模式：可离线单测，未来接 SSH/驱动后复用同一 payload 结构。
约定：无法识别到行时抛 ValueError（含示例提示），解析成功返回 {"count":N,"rows":[...],"summary":{...}}。
"""
import re
from collections import Counter


def _hint(kind, example):
    raise ValueError(f"未能从粘贴文本识别到任何 {kind} 条目；请粘贴设备输出原文（可含表头/页脚行）。示例开头：\n{example}")


# ---------- acl：Cisco ASA/FTD `show access-list` ----------
ACL_RE = re.compile(
    r"^\s*access-list\s+(\S+)\s+(?:line\s+\d+\s+)?extended\s+(permit|deny)\s+(\S+)\s*(.*)$",
    re.I)
ACL_HIT = re.compile(r"\(hitcnt=(\d+)\)")


def parse_acl(text):
    rows = []
    for line in text.splitlines():
        m = ACL_RE.match(line)
        if not m:
            continue
        name, action, proto, rest = m.groups()
        spec = re.sub(r"\(hitcnt=\d+\)", "", rest).strip()
        hit = ACL_HIT.search(line)
        rows.append({"name": name, "action": action.lower(), "protocol": proto.lower(),
                     "spec": spec, "hitcnt": int(hit.group(1)) if hit else None})
    if not rows:
        _hint("ACL", 'access-list ACL-OUT extended permit tcp host 10.1.1.1 host 8.8.8.8 eq 443 (hitcnt=1234)')
    return {"count": len(rows), "rows": rows,
            "summary": dict(Counter(r["action"] for r in rows))}


# ---------- nat：FortiOS `show firewall vip`（VIP 端口映射块） ----------
def parse_nat(text):
    rows, cur = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("config firewall vip") or line.startswith("end"):
            continue
        em = re.match(r'^edit\s+"?([^"]+)"?$', line)
        if em:
            cur = {"name": em.group(1), "extip": "", "mappedip": "", "extintf": ""}
            continue
        if cur:
            kv = re.match(r"^set\s+(\S+)\s+(.+)$", line)
            if kv:
                key, val = kv.group(1), kv.group(2).strip().strip('"')
                if key in cur:
                    cur[key] = val
            if line.startswith("next"):
                if cur["extip"] or cur["mappedip"]:
                    rows.append(cur)
                cur = None
    if not rows:
        _hint("NAT(VIP)", 'config firewall vip\n  edit "web-https"\n'
                          '    set extip 203.0.113.10\n    set mappedip "10.0.0.8"\n'
                          '    set extintf "wan1"\n  next\nend')
    return {"count": len(rows), "rows": rows,
            "summary": {"vip": len(rows)}}


# ---------- ipsec：FortiOS `get vpn ipsec tunnel status` ----------
IPSEC_RE = re.compile(
    r"^\s*name:\s+([\w.-]+)\((\d+)\)\s+proto=(\w+)\s+peer=([\d.]+)\s+local=([\d.]+)\s+status=(\w+)",
    re.I)


def parse_ipsec(text):
    rows = []
    for line in text.splitlines():
        m = IPSEC_RE.match(line)
        if not m:
            continue
        name, tid, proto, peer, local, status = m.groups()
        rows.append({"name": name, "id": int(tid), "proto": proto.lower(),
                     "peer": peer, "local": local, "status": status.lower()})
    if not rows:
        _hint("IPSec", 'name: branch1(101) proto=ikev2 peer=203.0.113.2 local=203.0.113.10 status=up')
    return {"count": len(rows), "rows": rows,
            "summary": dict(Counter(r["status"] for r in rows))}


PARSERS = {"acl": parse_acl, "nat": parse_nat, "ipsec": parse_ipsec}
KIND_LABELS = {"acl": "ACL 策略", "nat": "NAT/VIP", "ipsec": "IPSec 隧道"}
KIND_HINTS = {
    "acl": "粘贴 Cisco ASA/FTD：show access-list",
    "nat": "粘贴 FortiOS：show firewall vip",
    "ipsec": "粘贴 FortiOS：get vpn ipsec tunnel status",
}
