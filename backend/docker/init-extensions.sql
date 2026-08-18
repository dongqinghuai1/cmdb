-- 初始化扩展（ER V1.1：EXCLUDE 需 btree_gist；全局搜索需 pg_trgm）
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
