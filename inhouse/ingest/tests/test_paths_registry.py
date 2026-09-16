# -*- coding: utf-8 -*-
"""ingest 디렉토리 계약(landing/processing/data_lake)·소스 그룹 레지스트리·체인 순서·prune 판정 —
DB·LLM 없이 검사한다.
    cd inhouse && python -m unittest ingest/tests/test_paths_registry.py
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ingest import paths as P  # noqa: E402
from ingest import prune  # noqa: E402
from ingest import registry as R  # noqa: E402
from ingest.run_chain import STEP_NAMES, build_steps  # noqa: E402
from ingest.vectorize.build_pgvector_okf import SOURCE_GROUPS as PGV_GROUPS  # noqa: E402
from rag_core.retrieval.access import PRIVATE_ONLY_SOURCE_GROUPS  # noqa: E402

INHOUSE = Path(__file__).resolve().parents[2]
REPO = INHOUSE.parent


class PathsTest(unittest.TestCase):
    def test_legacy_defaults_match_pre_20260916_constants(self):
        """빈 설정 → 2026-09-16 이전 소스트리 고정 경로와 정확히 같아야(기존 배포 무변경)."""
        p = P.resolve_paths("", "", "")
        self.assertTrue(p.legacy)
        self.assertEqual(p.okf_documents, INHOUSE / "data_lake/semi_structure/okf_documents")
        self.assertEqual(p.pageindex_trees, INHOUSE / "data_lake/semi_structure/pageindex_trees")
        self.assertEqual(p.extract_dir("usgs"), INHOUSE / "data_lake/semi_structure/pdf_extract/usgs")
        self.assertEqual(p.extract_dir("mines"), INHOUSE / "data_lake/semi_structure/pdf_extract/mines")
        self.assertEqual(p.ocr_cache, INHOUSE / "data_lake/semi_structure/pdf_extract/_ocr_cache")
        self.assertEqual(p.shareable, INHOUSE / "data_lake/semi_structure/pdf_extract/shareable")
        self.assertEqual(p.restricted, INHOUSE / "data_lake/semi_structure/pdf_extract/restricted_diagnosis_only")
        self.assertEqual(p.landing_root("usgs", REPO / "documents/3. 생산매장량(USGS)"), REPO / "documents/3. 생산매장량(USGS)")

    def test_layout_overrides(self):
        with tempfile.TemporaryDirectory() as d:
            p = P.resolve_paths(f"{d}/landing", f"{d}/processing", f"{d}/lake")
            self.assertFalse(p.legacy)
            self.assertEqual(p.landing_root("usgs", REPO / "documents/x"), Path(d).resolve() / "landing/usgs")
            self.assertEqual(p.okf_documents, Path(d).resolve() / "lake/okf_documents")
            self.assertEqual(p.extract_dir("argus"), Path(d).resolve() / "processing/argus")
            self.assertEqual(p.logs.parent, Path(d).resolve() / "processing")
            self.assertEqual(p.as_dict()["mode"], "layout")

    def test_env_wins_over_settings(self):
        old = {k: os.environ.get(k) for k in ("INGEST_LANDING_DIR", "INGEST_PROCESSING_DIR", "INGEST_DATA_LAKE_DIR")}
        try:
            os.environ["INGEST_DATA_LAKE_DIR"] = "/tmp/x_lake"
            P.get_paths.cache_clear()
            self.assertEqual(P.get_paths().data_lake, Path("/tmp/x_lake"))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            P.get_paths.cache_clear()


class RegistryTest(unittest.TestCase):
    def test_out_dirnames_unique_and_stable(self):
        names = [g.out_dirname for g in R.GROUPS]
        self.assertEqual(len(names), len(set(names)))
        # doc_chunk.src·PageIndex source_group과 맞물린 불변 이름
        self.assertEqual(set(R.OKF_SOURCE_GROUPS), {"생산매장량_USGS", "조달청보고서", "Argus_비철금속_일일", "광산자료"})
        self.assertEqual(tuple(PGV_GROUPS), R.OKF_SOURCE_GROUPS)

    def test_private_only_matches_access_policy(self):
        """public 프로필 제외 목록(rag_core/retrieval/access.py)과 레지스트리가 어긋나면 안 됨."""
        self.assertEqual(R.PRIVATE_ONLY_OUT_DIRNAMES, PRIVATE_ONLY_SOURCE_GROUPS)

    def test_paid_only_argus(self):
        self.assertEqual([g.key for g in R.GROUPS if g.allow_paid], ["argus"])

    def test_landing_subdirs_are_simple(self):
        for g in R.GROUPS:
            self.assertRegex(g.landing_subdir, r"^[a-z0-9_]+$", g.key)
            self.assertNotIn("/", g.landing_subdir)

    def test_describe_has_all_groups(self):
        d = R.describe()
        self.assertEqual([x["key"] for x in d], [g.key for g in R.GROUPS])
        self.assertTrue(all("exists" in x for x in d))


class ChainTest(unittest.TestCase):
    def test_step_order_invariant(self):
        """pgvector_index(전량 DELETE) → pgvector_okf(src 단위) 순서, okf가 두 적재보다 앞."""
        names = list(STEP_NAMES)
        self.assertLess(names.index("okf"), names.index("pgvector_index"))
        self.assertLess(names.index("pgvector_index"), names.index("pgvector_okf"))
        self.assertLess(names.index("pgvector_okf"), names.index("prune"))
        self.assertEqual(names[-1], "prune")

    def test_llm_down_falls_back_to_no_summary(self):
        steps = {s.name: s for s in build_steps(prune_apply=False, llm_alive=False)}
        self.assertIn("--no-summary", steps["pageindex"].argv)
        steps = {s.name: s for s in build_steps(prune_apply=True, llm_alive=True)}
        self.assertNotIn("--no-summary", steps["pageindex"].argv)
        self.assertIn("--apply", steps["prune"].argv)
        self.assertTrue(steps["okf"].critical and steps["pgvector_okf"].critical)
        self.assertFalse(steps["pageindex"].critical)


def _write_okf(path: Path, doc_id: str, group_key: str, rel: str, resource: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    front = {"doc_id": doc_id, "source_group": "x", "group_key": group_key, "source_relative_path": rel}
    if resource:
        front["resource"] = resource
    import yaml

    path.write_text("---\n" + yaml.safe_dump(front, allow_unicode=True) + "---\n\n# t\nbody\n", encoding="utf-8")


class PruneTest(unittest.TestCase):
    def test_scan_and_apply_files_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            paths = P.resolve_paths(f"{d}/landing", f"{d}/processing", f"{d}/lake")
            mines = R.get_group("mines")
            landing = root / "landing" / mines.landing_subdir / "니켈"
            landing.mkdir(parents=True)
            (landing / "keep.pdf").write_bytes(b"%PDF-1.4 keep")
            okf_dir = paths.okf_documents / mines.out_dirname / "니켈"
            _write_okf(okf_dir / "keep.md", "doc_keep0000000001", "mines", "니켈/keep.pdf")
            _write_okf(okf_dir / "gone.md", "doc_gone0000000001", "mines", "니켈/gone.pdf")
            _write_okf(okf_dir / "unknown.md", "doc_unk", "mines", "")  # 판정 불가 → 보존
            tree = paths.pageindex_trees / mines.out_dirname / "니켈" / "gone.tree.json"
            tree.parent.mkdir(parents=True)
            tree.write_text("{}")
            old = {k: os.environ.get(k) for k in ("INGEST_LANDING_DIR", "INGEST_PROCESSING_DIR", "INGEST_DATA_LAKE_DIR")}
            try:
                os.environ["INGEST_LANDING_DIR"] = f"{d}/landing"
                os.environ["INGEST_PROCESSING_DIR"] = f"{d}/processing"
                os.environ["INGEST_DATA_LAKE_DIR"] = f"{d}/lake"
                P.get_paths.cache_clear()
                rep = prune.scan(paths, (mines,))
                self.assertEqual([o.okf_path.name for o in rep.orphans], ["gone.md"])
                self.assertEqual(rep.scanned["mines"], 3)
                res = prune.apply(rep, db=False)
                self.assertEqual(res["removed_files"], 2)
                self.assertFalse((okf_dir / "gone.md").exists())
                self.assertFalse(tree.exists())
                self.assertTrue((okf_dir / "keep.md").exists() and (okf_dir / "unknown.md").exists())
                # 50% 초과 삭제는 거부
                _write_okf(okf_dir / "gone2.md", "doc_g2", "mines", "니켈/gone2.pdf")
                _write_okf(okf_dir / "gone3.md", "doc_g3", "mines", "니켈/gone3.pdf")
                _write_okf(okf_dir / "gone4.md", "doc_g4", "mines", "니켈/gone4.pdf")  # 3/5 = 60% > 50%
                rep2 = prune.scan(paths, (mines,))
                self.assertIn("mines", rep2.refused_groups)
                self.assertEqual(rep2.orphans, [])
                # landing 루트가 비어 있으면 그룹 통째로 건너뜀
                (landing / "keep.pdf").unlink()
                rep3 = prune.scan(paths, (mines,))
                self.assertIn("mines", rep3.skipped_groups)
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
                P.get_paths.cache_clear()


class ResourceCompatTest(unittest.TestCase):
    """레거시 모드에서 OKF `resource`(= doc_chunk.source_path)가 2026-09-16 이전 표기와 같아야 한다."""

    def test_resource_paths_unchanged_in_legacy_mode(self):
        from ingest.okf.build_okf_documents import _resource_of

        usgs = R.get_group("usgs")
        self.assertEqual(_resource_of(usgs, usgs.legacy_root, "3. 생산매장량(USGS)/USGS_2026.pdf"),
                         "documents/3. 생산매장량(USGS)/USGS_2026.pdf")
        argus = R.get_group("argus")
        self.assertEqual(_resource_of(argus, argus.legacy_root, f"{argus.legacy_root.name}/x.pdf"),
                         "documents/보고서_2/Argus Metal_비철금속_2023~2026_일일 (1)/x.pdf")
        mines = R.get_group("mines")  # nas_document 심볼릭링크: resolve하지 않은 표기 유지
        self.assertEqual(_resource_of(mines, mines.legacy_root, "학습데이터/니켈/a.pdf"),
                         "nas_document/학습데이터/니켈/a.pdf")
        with tempfile.TemporaryDirectory() as d:  # 저장소 밖 landing 마운트 → <key>/<상대경로>
            root = Path(d) / "mines"
            root.mkdir()
            self.assertEqual(_resource_of(mines, root, "mines/니켈/a.pdf"), "mines/니켈/a.pdf")


if __name__ == "__main__":
    unittest.main()
