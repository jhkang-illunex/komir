from .page_index import *
from .page_index_md import md_to_tree
from .retrieve import get_document, get_document_structure, get_page_content
from .tree_optimize import optimize_tree

# client.py(PageIndexClient, https://api.pageindex.ai 유료 클라우드 REST 클라이언트)는
# 2026-08-11 vendoring 시 의도적으로 제거했다 — airgap 환경에서 실수로라도 문서를
# 외부로 업로드하는 코드가 아예 존재하지 않게 하기 위함(services/shared/
# pageindex_vendor/README.md 참고).
