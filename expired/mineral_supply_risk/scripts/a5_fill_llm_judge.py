# -*- coding: utf-8 -*-
"""A-5 LLM 교차판정(Claude) 채움 — ⚠ 사람 검증 아님 (2026-07-27).

사용자가 옵션(하이브리드/순수 LLM judge/축소 사람판정/2인 교차) 중 **"순수 LLM
judge"를 한계를 인지한 상태로 명시 선택**해 수행. 추출은 로컬 vLLM, 판정은
Claude(다른 모델)라 문자 그대로의 자기채점은 아니지만, LLM 간 계통 편향 공유
가능성 때문에 이 결과는:
  - **A-5(사람 라벨 검증) 완료로 보고 금지** — 발주처 보고서에는 "교차 모델
    일관성 점검"으로만 기재 가능
  - 실제 사람 판정이 이뤄지면 이 파일과 무관하게 원본 배포 파일
    (a5_review_A/B_260727.csv)로 처음부터 진행

판정 방법: LLM 값이 제거된 검토자용 사본(a5_review_A_260727.csv)의
evidence_quote 250건을 Claude가 전건 직접 읽고 severity·direction·event_type
적절성을 독립 판정(가이드 v2 기준, 판단불가 10건은 강제 채움 없이 표기).
JUDGMENTS 상수가 판정 원본 기록(재현용).

실행: python3 -m scripts.a5_fill_llm_judge
산출: outputs/model_opt/a5_review_llmjudge_claude_260727.csv
채점: python3 -m scripts.a5_kappa_score \
        --input outputs/model_opt/a5_review_llmjudge_claude_260727.csv \
        --master outputs/model_opt/a5_review_sample_260727.csv \
        --out outputs/model_opt/a5_kappa_report_llmjudge_260727.md
"""
from __future__ import annotations
import os

import pandas as pd

from msr.config import OUT

# event_id  severity(0~3|X=판단불가)  direction(7종|X)  event_type적절성(Y/N/부분)
JUDGMENTS = (
    "cfed115111677264 2 price_up 부분|47ef5124d811d8b7 0 neutral N|"
    "1a6c8ffabc58213b 2 supply_down Y|53d969b5cb2d6338 0 price_up N|"
    "eb7080fa9faacf13 1 supply_up Y|4c7b2f3b392d31bc X X N|"
    "1f157cf8b9fc2219 2 supply_down Y|6da386d9141288a2 1 neutral 부분|"
    "233008e60c3270a3 0 neutral N|f3f64d34bea2328e 1 supply_up N|"
    "e096ff1767b2617a 0 neutral N|27cd0bceaa312100 1 supply_up Y|"
    "727168f0689ea4b9 2 supply_down Y|1090f1d22a57f629 2 supply_down Y|"
    "2b7c18125d1c765c 0 price_up 부분|6c6299cb39baedf1 2 neutral Y|"
    "cd9d5adf8ea1153a 1 supply_up Y|2120d9db5ff363cd 0 neutral N|"
    "d54863507ad54351 3 supply_down Y|6b50ed57a40d95d8 0 neutral 부분|"
    "8d7859e500ce45de 0 neutral Y|9451f16c441446d2 0 neutral N|"
    "beb88dc6726edd0a 1 supply_up Y|941bedea3c7c13f9 1 supply_up Y|"
    "94b465a449b993e9 2 neutral Y|fd92d9c666892e66 1 supply_down Y|"
    "5593ec30e7d6994b 0 neutral N|6c2d5a8235760f34 0 neutral N|"
    "e9deb3a978973d7d 0 neutral N|8bb5595501a3e6f2 0 neutral Y|"
    "48bfb225f20a0da6 0 neutral N|cebc2e3eb15fcb73 2 supply_down Y|"
    "1774f1d43512b9b6 1 price_down Y|c869bef172b7b66b X X N|"
    "e89233c093fb5d49 2 supply_down Y|f52eddd962d92952 X X N|"
    "13f6ba75a5777e06 0 neutral 부분|e77c20a72dbd816e 3 supply_down Y|"
    "dd8780c58d8428d8 2 supply_down Y|fc4007d525dac911 0 neutral N|"
    "540a1c31adace27b 2 supply_up Y|cbef022d266b36aa 1 neutral Y|"
    "953d8f8182dd9567 0 neutral N|e39b9bd42043dbe1 2 price_up Y|"
    "3aef6510394bc386 0 neutral N|90869400a3549d84 0 neutral N|"
    "cb6c870ab2e29b63 3 supply_down Y|0a2b5709f18fcd68 1 neutral Y|"
    "384fc29691afa2c0 0 neutral 부분|34d77f5328be4934 2 supply_down Y|"
    "894485ed588b7600 2 supply_down Y|8a3d71e300a1f8d9 2 supply_down Y|"
    "84e29832f613bacf 2 supply_up Y|128780f094a94e1c 0 neutral 부분|"
    "4efad4b5d174ce1d 2 supply_down Y|12de543a6fea5727 1 supply_up Y|"
    "0f5d154901433edb X X N|5ba7eeea9ba84fc7 1 neutral N|"
    "65d4053c7b5842f1 0 neutral N|ea88d4b0fc749448 1 neutral Y|"
    "5ec0813db5e80805 1 supply_up Y|e29ba410fa64f1d8 1 supply_up N|"
    "97e2ce5dd94547a9 1 supply_up Y|e9db1d8dc8a8f310 2 supply_down Y|"
    "676a40dbd80fb288 1 supply_down Y|1b03695fb35ba09e 1 supply_up Y|"
    "ad483f8c9754d5be 2 supply_down Y|1ff248a3037c2112 0 neutral N|"
    "cb6720b0cadb6b75 1 neutral Y|e25c23cc9ac7ac43 1 supply_up Y|"
    "2bffe653324fee54 0 neutral N|95bfa806c2973059 0 neutral N|"
    "dbcb3cab3209c11e 0 neutral N|35be2228aee6b2b3 0 demand_up 부분|"
    "ed45151a4c8b9eb1 2 supply_down Y|9f96511d35dc20a7 1 supply_up Y|"
    "502439641be832f2 2 supply_down 부분|845eae9537cd6978 0 neutral Y|"
    "0d914c4b6c3b1b45 2 supply_down Y|ce5312a329d22054 0 neutral N|"
    "9b0d22157d765e2b 1 supply_up N|ed736c1173fa07a6 0 neutral N|"
    "1561b186256acfff 2 supply_down Y|68a188db72d05eb5 2 supply_down Y|"
    "d05c1fb9323f38e7 1 neutral Y|7e0ec76e9f9abc99 0 neutral N|"
    "0d39e43497de1c9f 2 supply_down Y|403637f95f9d5bed 1 neutral Y|"
    "50d44f7b03e92a63 1 neutral Y|3902f2644015f3a4 0 neutral N|"
    "2c0a9af24885831b 1 supply_down Y|299cb3de2a67527b 0 neutral N|"
    "e76a94a80fe6d5ed 0 neutral Y|81424863c225873f 0 neutral N|"
    "7cd7760805adc11a 2 supply_down Y|9c5f334777fc7f2c 0 neutral N|"
    "fed5a7781471b08f 1 neutral N|3dbaa105df9c9f7e 0 neutral N|"
    "6ab96b43a813cbb1 0 neutral N|baaa05adc810ebfc 0 neutral N|"
    "89c5ef41d5ed1d4f 0 neutral N|5c9181cb1dadfeb7 2 supply_down Y|"
    "afd2086241043936 2 price_up Y|d3e87423d817671a 1 supply_down Y|"
    "a09de3c89f07168c 3 supply_down Y|35478f3fe5ae038b 1 neutral Y|"
    "d4784803b9c5814c 1 neutral Y|5202ec5e64e5467b X X N|"
    "88a06fe0452c449c 2 supply_down Y|38f8b026ef2920e2 1 demand_up Y|"
    "6c7d395f40e19dde 2 supply_up Y|aa05819da7be035c 2 supply_down Y|"
    "8087c2f7a4725d62 1 price_down N|b3c57273040fa16c 2 supply_down Y|"
    "f7068f6250939e66 0 neutral Y|46851e6795a1153e 1 supply_up N|"
    "4a073b9559b61f51 0 neutral N|c91319f3f153097c 0 neutral 부분|"
    "52888fb3567dbbbc 2 supply_down Y|d337bc4fea7c06ff 0 neutral N|"
    "55cc5da9883b77fb 0 neutral Y|ae8e0601481e9a25 0 neutral N|"
    "ff4416a9645951dc 2 supply_down Y|20d9a50d0440a183 0 neutral 부분|"
    "d95a7b1902b93ae0 0 neutral 부분|898704d5f69d44c1 1 neutral Y|"
    "3d93c26faa2b9925 1 neutral Y|01b43f335c0b62ae 0 neutral N|"
    "c0741eaf061342e8 1 neutral Y|01d6154215e4b70f X X N|"
    "4c30bc1e3182649f 0 neutral N|8fbfae532bca29de 2 supply_down Y|"
    "4b5e1d6d6c13e701 0 neutral N|ece7297069cf72df 0 neutral Y|"
    "dec9ed9741182cc4 1 neutral 부분|b9921977f4a00afe 2 supply_up Y|"
    "f5df270bd9ba33f8 0 neutral N|242feca95e4c457b 0 neutral N|"
    "fdb2057932506f82 1 supply_up Y|230f241012a66d87 1 supply_up Y|"
    "bc35e529c98ef6bf 1 neutral Y|4f607bddd2a7bdad 2 supply_up Y|"
    "bb1d229e04818ff4 2 supply_down Y|9d4eabb2459798b3 1 demand_up Y|"
    "d3cde1c88d89d663 X X N|f05c2554187c7845 1 supply_up 부분|"
    "d98ce72d93201f25 2 neutral Y|98a9606e68dae6db 0 neutral N|"
    "988aa711cdb4b3a2 1 neutral Y|d2d26e04b9c86084 3 supply_down Y|"
    "fa7646622c20c06d 0 neutral N|bba12275e6104d87 X X N|"
    "a026bbb7817b0e34 0 neutral Y|62ca40dcaa221bd3 1 supply_down Y|"
    "08e5c6f6ea339edb 1 neutral Y|c1c50dde1eda5d9a 0 neutral N|"
    "bf690338c7e1cfc9 0 neutral Y|972641b72e29c104 0 neutral N|"
    "ba66a9a236d1059a 1 neutral Y|bbe3383d2452b182 1 neutral Y|"
    "8a4d2f45809e6afa 1 neutral Y|7902e6f55379a960 0 neutral N|"
    "a570bc3d415effe5 1 price_down Y|6e4f4d68a560dc50 1 neutral Y|"
    "f2b3f602bb6f4eda 1 neutral 부분|bd210eacae2d9c1b 0 neutral N|"
    "35181794f9d453d3 1 neutral Y|5e8bd82096cfe965 2 supply_down Y|"
    "32469f30c109e044 2 supply_up Y|6cbd88cd50f25b54 0 neutral N|"
    "976c159d7f333534 0 demand_up N|9cf2d4a6131cda1e 0 neutral N|"
    "6b0f68819e6b0a4b 1 supply_down Y|f146346cd75719a4 2 supply_down Y|"
    "7309f7e20a6fdfe9 2 neutral Y|f3896cf35c40dac3 0 neutral 부분|"
    "bc5b1c2d3851f1ac 0 price_up N|b0421df81b4749ce 1 neutral Y|"
    "e9d0aaee493064f9 1 neutral Y|9b84ddcd34c8fd3d 1 neutral Y|"
    "158c5bcebb9a9eec 0 neutral N|8b432e6ea39c5025 0 neutral N|"
    "71682203bdd2adcf 1 price_down 부분|b93872486af8f699 0 neutral N|"
    "897eedec053f69c8 1 neutral 부분|7d96a93e2dc2fa10 0 neutral N|"
    "72715e5653955a33 0 neutral Y|1d7ec26acaf71a7d 1 supply_up Y|"
    "decf29285fcc365f 1 neutral Y|cb0948ce1d29ebfc 0 neutral N|"
    "57a746b32345a806 1 neutral Y|d9eeda589c0ebe0a X X N|"
    "7ad4af8f63e8fc6c 0 neutral 부분|3f16c3bb28a2078e 2 supply_down 부분|"
    "787a0484a275bf0f 1 neutral N|cc1a31cf6c7be8a1 1 demand_up 부분|"
    "dd5fb81ca25a583f 0 neutral 부분|5f8ea197294da9ab 0 neutral Y|"
    "aa2861599d6d8f5b 2 supply_up Y|ec857b62446bc885 0 neutral N|"
    "9a4faf0ec4ee34e8 1 supply_up Y|5ff218d0d7859e52 1 supply_up Y|"
    "9c811d171f7b2fa2 1 neutral N|f29b4d077ee66cc6 0 neutral N|"
    "9ad7e0143285d080 0 neutral N|d1108de1e5808f42 0 neutral Y|"
    "63f62063ba522689 1 neutral Y|9d35ff603ae9a829 0 neutral N|"
    "2df3a96ce79c5e1c 3 supply_down Y|1e8321423a6bb64f 2 supply_down Y|"
    "da88cc3b9abdb4a0 1 supply_up N|764447d075510d83 0 neutral Y|"
    "4fafa58d08af55eb 1 price_up Y|69ae5f2c6b444e7f 0 neutral N|"
    "b5ac9518ffb2ac78 1 supply_up Y|9d7bba7637bdc647 X X N|"
    "e6f2d1dd3815ed9c 0 neutral N|59ab99a23c635091 0 neutral N|"
    "b25705c2e9332e4f 0 neutral N|a198a179599bf7f5 0 neutral N|"
    "52a26e72e0869121 2 supply_down Y|e2c9308a1ad6425e 2 supply_down Y|"
    "a711975dba34549e 1 neutral Y|1fed5a73f381c00a 1 demand_up 부분|"
    "3c625c8919684b01 2 supply_down Y|c1f678ef47204f3c 0 neutral N|"
    "4ab78f7fca6ec5f0 1 neutral Y|24a8836801976b86 0 neutral N|"
    "c54a946a8a48b144 0 neutral N|50acdef99d606c99 2 supply_down Y|"
    "e7c47b413cd685a9 1 supply_up 부분|9348a27ff965452c 0 neutral N|"
    "13ea423d4aefefce 0 neutral N|2234cc774de25f65 0 neutral Y|"
    "aee168139d2b4081 0 neutral Y|fe0c33acf2eea1b5 0 neutral N|"
    "e5af5e230beff76f 0 neutral N|8fefddad02e09e17 2 supply_down Y|"
    "aa1cb5dfd29a1e0c 0 neutral Y|20f558c935e83666 0 neutral N|"
    "e9c753bdff3ca220 0 demand_up N|6197ef163439dfff 1 neutral Y|"
    "632ea33088de7646 0 neutral N|c7b9e9acfc651761 2 supply_down Y|"
    "e8f021505d4a23ae 1 supply_up Y|a370052b125bc543 1 supply_up N|"
    "8669871be5681a8d 0 neutral Y|1fe20625adbda83a 1 price_down 부분|"
    "634c28d7b522ddfd 1 price_down Y|6920eaef98a7199a 0 neutral N"
)

# 판정 중 발견한 오태깅·무관 콘텐츠(부산물 — 참고용이어도 실가치, 07-20 전례)
NOTES = {
    "e9deb3a978973d7d": "무관 의심(구리 위생효과 건강기사)",
    "953d8f8182dd9567": "오태깅 의심(다이아몬드 광산 Gahcho Kué→LI)",
    "2bffe653324fee54": "무관 의심(3D프린팅 소재 기사)",
    "95bfa806c2973059": "오태깅 의심(석유회사 Cobalt International Energy→CO)",
    "7e0ec76e9f9abc99": "무관 의심(무전해 니켈 도금 기술기사)",
    "2c0a9af24885831b": "오태깅 의심(금광 Bulyanhulu→CU, 국가 Mali도 오류)",
    "3dbaa105df9c9f7e": "무관 의심(수돗물 납·구리 기사→NI)",
    "d3e87423d817671a": "오태깅 의심(구리·석탄 항만 폐쇄→CO)",
    "ae8e0601481e9a25": "무관 의심(Teck 석탄 스핀오프→CO)",
    "bba12275e6104d87": "지명성 콘텐츠 의심(Port Coquitlam)",
    "972641b72e29c104": "오태깅 의심(가넷·구리 tailings→REE)",
    "8b432e6ea39c5025": "무관 의심(구리광산 지역 역사 기사)",
    "7d96a93e2dc2fa10": "오태깅 의심(선거구명 'Nickel Belt' 정치기사→NI)",
    "69ae5f2c6b444e7f": "무관 의심(프레퍼 배터리 콘텐츠)",
    "c54a946a8a48b144": "무관 의심(광산지역 타이어 매장 기사)",
    "fe0c33acf2eea1b5": "무관 의심(런던 증시 마감시황, ET '제재' 부적절)",
}
WARNING = ("⚠ LLM 교차판정(Claude) — 사람 검증 아님. A-5 완료로 보고 금지, "
           "발주처 보고서에는 '교차 모델 일관성 점검'으로만 기재")


def run():
    out_dir = os.path.join(str(OUT), "model_opt")
    base = pd.read_csv(os.path.join(out_dir, "a5_review_A_260727.csv"),
                       encoding="utf-8-sig")
    jm = {}
    for ent in JUDGMENTS.split("|"):
        eid, sev, drc, et = ent.split()
        jm[eid] = ("판단불가" if sev == "X" else sev,
                   "판단불가" if drc == "X" else drc, et)
    assert set(jm) == set(base["event_id"]), "표본-판정 event_id 불일치"

    base["severity_사람판정"] = base["event_id"].map(lambda i: jm[i][0])
    base["direction_사람판정"] = base["event_id"].map(lambda i: jm[i][1])
    base["event_type_적절성(Y/N/부분)"] = base["event_id"].map(lambda i: jm[i][2])
    base["비고"] = base["event_id"].map(lambda i: NOTES.get(i, ""))
    base.insert(0, "경고", WARNING)

    path = os.path.join(out_dir, "a5_review_llmjudge_claude_260727.csv")
    base.to_csv(path, index=False, encoding="utf-8-sig")
    n_na = (base["severity_사람판정"] == "판단불가").sum()
    print(f"[a5_fill_llm_judge] {len(base)}건 채움(판단불가 {n_na}건, "
          f"오태깅·무관 의심 비고 {sum(1 for v in base['비고'] if v)}건) → {path}")
    print(WARNING)


if __name__ == "__main__":
    run()
