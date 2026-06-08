-- ============================================================================
-- Prod Postgres: diagnose what is using the disk, then reclaim it safely.
--
-- Context: the prod volume (~0.48 GB) is essentially full, which made the
-- Text->JSONB migrations fail with DiskFull while rewriting tables. This kit
-- (1) shows what is actually consuming space and (2) reclaims it.
--
-- HOW TO RUN
--   Diagnostics only (SAFE, read-only):
--     psql "$DATABASE_URL" -f scripts/prod_disk_diagnose_reclaim.sql
--   (Run WITHOUT `-v ON_ERROR_STOP=1` -- psql's default continues past a failed
--    query, so if the optional WAL check lacks privileges the rest still runs.)
--   On Railway you can also: `railway connect Postgres` then `\i <this file>`.
--   Reclaim is in PART B below and is COMMENTED OUT on purpose -- read PART A
--   first, decide what to delete, then run the PART B statements by hand.
--
-- KEY FACT: DELETE does NOT shrink the volume. Deleted rows only become
-- reusable space *inside* the table file. To return space to the OS you must
-- VACUUM FULL (or pg_repack) the table, which rewrites it and needs temporary
-- free space ~= the table's size. So reclaim SMALLEST-first to free headroom
-- progressively, and never assume a DELETE alone freed disk.
-- ============================================================================


-- ============================================================================
-- PART A — DIAGNOSE (safe, read-only)
-- ============================================================================

\echo '== total database size =='
SELECT pg_size_pretty(pg_database_size(current_database())) AS db_size;

\echo ''
\echo '== top 25 relations by total size (heap + indexes + TOAST) =='
SELECT
    n.nspname                                                     AS schema,
    c.relname                                                     AS object,
    c.relkind                                                     AS kind,   -- r=table, i=index, t=toast, m=matview
    pg_size_pretty(pg_total_relation_size(c.oid))                 AS total,
    pg_size_pretty(pg_relation_size(c.oid))                       AS heap,
    pg_size_pretty(pg_indexes_size(c.oid))                        AS indexes,
    pg_size_pretty(
        pg_total_relation_size(c.oid)
        - pg_relation_size(c.oid)
        - pg_indexes_size(c.oid))                                 AS toast
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT 25;

\echo ''
\echo '== bloat / vacuum candidates (high dead_pct = lots of reclaimable space) =='
SELECT
    relname                                                       AS table,
    n_live_tup                                                    AS live,
    n_dead_tup                                                    AS dead,
    round(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 1) AS dead_pct,
    last_vacuum,
    last_autovacuum
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC
LIMIT 25;

\echo ''
\echo '== WAL on disk (leftover write-ahead logs can be large; needs monitor/superuser) =='
-- If this errors with "permission denied", skip it -- it just means the role
-- cannot read pg_wal; it is informational only.
SELECT count(*) AS wal_files, pg_size_pretty(sum(size)) AS wal_total
FROM pg_ls_waldir();

\echo ''
\echo '== row counts for the big legacy tables (decide what is unwanted) =='
SELECT 'scan_citations'      AS tbl, count(*) FROM scan_citations
UNION ALL SELECT 'source_profiles',     count(*) FROM source_profiles
UNION ALL SELECT 'scan_results',        count(*) FROM scan_results
UNION ALL SELECT 'scans',               count(*) FROM scans
UNION ALL SELECT 'actions',             count(*) FROM actions
UNION ALL SELECT 'kb_chunks',           count(*) FROM kb_chunks
UNION ALL SELECT 'crawl_pages',         count(*) FROM crawl_pages
UNION ALL SELECT 'extraction_evidence', count(*) FROM extraction_evidence
UNION ALL SELECT 'crawl_business_profiles', count(*) FROM crawl_business_profiles
UNION ALL SELECT 'onboarding_workspaces',   count(*) FROM onboarding_workspaces
ORDER BY 2 DESC;

\echo ''
\echo '== scan_citations by client (find data that belongs to abandoned/test clients) =='
SELECT client_id, count(*)
FROM scan_citations
GROUP BY client_id
ORDER BY 2 DESC
LIMIT 20;


-- ============================================================================
-- PART B — RECLAIM (DESTRUCTIVE — run by hand, in order, after reviewing PART A)
--
-- All statements below are commented out. Uncomment/run deliberately.
-- VACUUM FULL takes an ACCESS EXCLUSIVE lock (the table is unavailable while it
-- runs) and needs free disk ~= the table size, so do it during low traffic and
-- go SMALLEST-first so each one frees headroom for the next.
-- ============================================================================

-- Step 1 — delete the rows you decided are unwanted (examples; adjust the WHERE!):
--   BEGIN;
--   DELETE FROM scan_citations WHERE client_id = '<abandoned-client-id>';
--   -- (FK cascades from migration 0020 will clean owned children automatically)
--   COMMIT;

-- Step 2 — force a checkpoint so WAL from the failed migrations can be recycled:
--   CHECKPOINT;

-- Step 3 — reclaim to the OS, smallest table first (watch db_size drop after each):
--   VACUUM (FULL, VERBOSE, ANALYZE) scans;
--   VACUUM (FULL, VERBOSE, ANALYZE) actions;
--   VACUUM (FULL, VERBOSE, ANALYZE) scan_results;
--   VACUUM (FULL, VERBOSE, ANALYZE) source_profiles;
--   VACUUM (FULL, VERBOSE, ANALYZE) scan_citations;     -- the big one; do it last

-- Step 4 — re-check size (should be well under the volume limit now):
--   SELECT pg_size_pretty(pg_database_size(current_database())) AS db_size;

-- If a VACUUM FULL itself fails with DiskFull (no headroom even for the rewrite),
-- you are out of runway on this volume: delete more from OTHER tables and VACUUM
-- FULL those first, or upsize the volume. pg_repack needs the same free space and
-- the extension installed, so it is not a way around a genuinely full disk.
