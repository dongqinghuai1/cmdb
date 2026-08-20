-- nops 数据库级约束（ER V1.1 D2/D3/D4/D7 + 4.6 告警去重）
-- 时机：python manage.py migrate 之后执行（表名按 Django 默认 app_model 命名）
-- 需要 btree_gist 扩展（docker/init-extensions.sql 已启用）

-- D2: 机柜 U 位排他（设备表内）
ALTER TABLE cmdb_device
ADD CONSTRAINT u_slot_excl
EXCLUDE USING gist (
    rack_id WITH =,
    int4range(rack_start_u, rack_start_u + rack_units) WITH &&
) WHERE (rack_id IS NOT NULL AND deleted_at IS NULL);

-- D2: 预留位排他（rack_reservation 表内；与设备的跨表互斥由 DeviceService 校验）
ALTER TABLE dcim_rackreservation
ADD CONSTRAINT reservation_slot_excl
EXCLUDE USING gist (
    rack_id WITH =,
    int4range(start_u, start_u + units) WITH &&
);

-- D3: 告警活跃事件唯一（巡检/监控共用去重键，关闭后可再触发）
CREATE UNIQUE INDEX IF NOT EXISTS alert_event_active_dedup
ON alert_alertevent (dedup_key)
WHERE status IN ('firing', 'acknowledged', 'processing');

-- D4: 占用/预约时间窗排他（同设备同窗口仅一人）
ALTER TABLE usage_deviceusage
ADD CONSTRAINT usage_window_excl
EXCLUDE USING gist (
    device_id WITH =,
    tstzrange(planned_start, planned_end) WITH &&
) WHERE (status IN ('reserved', 'active'));

-- D7: 线缆方向归一化
ALTER TABLE dcim_cable
ADD CONSTRAINT cable_dir_check CHECK (a_interface_id < b_interface_id);

-- 全局搜索 trgm（PRD 5.1，V1.1 评审 #7）
CREATE INDEX IF NOT EXISTS device_sn_trgm ON cmdb_device USING gin (sn gin_trgm_ops) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS device_hostname_trgm ON cmdb_device USING gin (hostname gin_trgm_ops) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS device_attrs_gin ON cmdb_device USING gin (attrs jsonb_path_ops) WHERE deleted_at IS NULL;

-- 唯一性约束（专家评审 P1：防重复 IP/SN 设备导致 syslog/采集错配）
CREATE UNIQUE INDEX IF NOT EXISTS device_sn_uq ON cmdb_device (sn) WHERE deleted_at IS NULL AND sn IS NOT NULL AND sn != '';
CREATE UNIQUE INDEX IF NOT EXISTS device_manage_ip_uq ON cmdb_device (manage_ip) WHERE deleted_at IS NULL AND manage_ip IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS device_asset_no_uq ON cmdb_device (asset_no) WHERE deleted_at IS NULL AND asset_no IS NOT NULL AND asset_no != '';

-- 平台自监控任务心跳指标
-- (由 monitor.self_check 写入 VM: platform_heartbeat)

-- 分区表说明（D12）：alert_login_event / monitor_logrecord / system_auditlog
-- 一期为普通表+索引（数据量见 ER 第 7 章），分区转换在量级到位后经 pg_partman 迁移。
