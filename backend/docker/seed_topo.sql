-- 拓扑演示数据：给三台交换机建接口并互相 LLDP 邻居
INSERT INTO cmdb_deviceinterface (device_id, name, if_index, if_alias, media_type, admin_status, oper_status, duplex, mac, vlan_ids, attrs, created_at, updated_at)
SELECT d.id, 'GE1/0/' || n, n, '', 'ethernet', 'up', 'up', 'full', '', '[]'::jsonb, '{}'::jsonb, now(), now()
FROM cmdb_device d, generate_series(1, 24) n
WHERE d.name IN ('SW-CORE-01','SW-ACC-02','SW-ACC-03')
ON CONFLICT DO NOTHING;

INSERT INTO topo_lldpneighbor (local_interface_id, source, remote_chassis_id, remote_hostname, remote_port_desc, remote_port_id, remote_device_id, first_seen_at, last_seen_at)
SELECT li.id, 'lldp', 'mac-'||rd.name, rd.name, ri.name, ri.name, rd.id, now(), now()
FROM cmdb_deviceinterface li
JOIN cmdb_device ld ON ld.id = li.device_id AND ld.name = 'SW-CORE-01' AND li.name = 'GE1/0/24'
JOIN cmdb_deviceinterface ri ON ri.name = 'GE1/0/1'
JOIN cmdb_device rd ON rd.id = ri.device_id AND rd.name IN ('SW-ACC-02','SW-ACC-03')
ON CONFLICT DO NOTHING;

INSERT INTO topo_lldpneighbor (local_interface_id, source, remote_chassis_id, remote_hostname, remote_port_desc, remote_port_id, remote_device_id, first_seen_at, last_seen_at)
SELECT li.id, 'lldp', 'mac-'||rd.name, rd.name, ri.name, ri.name, rd.id, now(), now()
FROM cmdb_deviceinterface li
JOIN cmdb_device ld ON ld.id = li.device_id AND ld.name IN ('SW-ACC-02','SW-ACC-03') AND li.name = 'GE1/0/2'
JOIN cmdb_deviceinterface ri ON ri.name = 'GE1/0/23'
JOIN cmdb_device rd ON rd.id = ri.device_id AND rd.name = 'FW-EXIT-01'
ON CONFLICT DO NOTHING;
