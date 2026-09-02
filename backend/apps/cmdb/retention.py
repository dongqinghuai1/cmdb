"""TechSnapshot 保留策略（服务层，供 celery 周期任务与按需接口共用）。

按 (device_id, kind) 分组只保留最近 keep 条（按 id 倒序=最新在前），
一次性批量删除更旧记录；孤儿（设备已 purge）同样参与分组限制增长。
注意：模型须在函数内惰性导入（celery autodiscover 阶段 django 尚未 ready）。
"""


def cleanup_techsnapshots(keep=5):
    from apps.cmdb.models import TechSnapshot
    keep = max(int(keep), 1)
    seen = {}
    to_delete = []
    # 倒序遍历：每条记录累计到组内第 keep+ 条即标记删除
    for pk, did, kind in (TechSnapshot.objects.order_by("-id")
                          .values_list("id", "device_id", "kind")):
        key = (did, kind)
        pos = seen.get(key, 0)
        if pos >= keep:
            to_delete.append(pk)
        else:
            seen[key] = pos + 1
    removed = 0
    if to_delete:
        removed, _ = TechSnapshot.objects.filter(id__in=to_delete).delete()
    return {"kept_groups": len(seen), "removed": removed, "keep": keep,
            "retained": TechSnapshot.objects.count()}
