BEGIN;
DELETE FROM mineral_risk.doc_chunk WHERE doc_id = ANY (ARRAY['e09bbbbdac2e3b3a','c5ba28f3421c6bb1','3b3b60baa05e7715','738ead83c52ecab7']);
INSERT INTO mineral_risk.doc_chunk SELECT * FROM mineral_risk.doc_chunk_backup_acceptance_20260923_205629;
COMMIT;
