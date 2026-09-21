# PageIndex·OKF 단건 조회 독립검증 (2026-09-22)

## 기준과 원천

- 평가 Q01~Q30 기준 응답: `/tmp/sol-action-full-r10f-260921/Q*.json`. Q15·Q21·Q22는 `document.retrieve` 경유 무인용 `source_unavailable`, Q30 원문은 서울 날씨·점심 메뉴여서 `out_of_scope`다. 새 intent가 이 경계를 바꾸면 회귀다.
- 실본문: `inhouse/data_lake/semi_structure/okf_documents/광산자료/우라늄/20260813_Kazatomprom_우라늄_광산_정리자료.md:32`에 `JV Inkai LLP | 45.281 | 67.536`, `광산자료/동_구리/Cu_Escondida_Pampa_Norte_BHP.md:33`에 `Escondida in Chile`. 둘의 PageIndex `.tree.json` 파일도 존재한다.
- 공개 접근 반례: `Argus_비철금속_일일/Argus_Non-Ferrous_Markets_2025-10-29.md`를 명시한 로컬 `pageindex.lookup('copper price', doc=...)`에서 public 필터는 문서 0·노드 0, private 무필터는 문서 1·노드 5였다. 새 공개 API가 이 원문을 공개하면 접근 경계 실패다.

## r1 수용 요청: 불합격

- 대상: `komir-rag-chat-okf-r1`, 이미지 `sha256:98f5c732626385d8ba25f09902e870d39eb95c0d86b4cabff0002dd3c47c9c45`, 18006 `/healthz` 정상. 질문·응답·원시 SSE/JSON: `/tmp/sol-okf-r1-accept-260922/`.

| 질문 | 실제 결과 | 판정 |
| --- | --- | --- |
| `JV Inkai 위치` | `mine.profile` stage 2/3 뒤 카자흐스탄만 답함. 인용 2건은 **U_Cigar Lake PDF**의 dense 청크이며 JV Inkai OKF 경도·위도 누락 | **P0: 잘못된 문서 인용**. graph는 PageIndex 본문이 하나 있는지만 확인하고 dense와 함께 생성에 넘겨 대상 문서 일치가 보장되지 않았다. |
| `BHP 보고서 Escondida 나라·원문` | `document.lookup` stage 3 `source_unavailable:okf_body_unavailable` | **P1: 실본문 존재에도 조회 실패**. OKF 33행 `Escondida in Chile` 있음. |
| `Kazatomprom 우라늄 광산 위치` | `mine.profile` stage 3 `source_unavailable:okf_body_unavailable` | 복수 광산 행을 구분하거나 범위를 명시해야 함. 현재 본문 폴백 실패. |
| JV Inkai 2026-09 수입액 | stage 1 `unsupported_combination` | 본문에 없는 수치를 만들지는 않았음. 기권 사유와 의도 분류는 후속 검토. |
| Argus 2025-10-29 공개 본문 | `document.lookup` stage 3 `source_unavailable`, 인용 0 | 공개 접근 필터 유지. |
| 리튬 매장량 광산 상위 5개 | `mine.rank` 답변, 집계 인용 1 | 기존 순위 경로 정상. |

컨테이너 로그에서도 Escondida·복수 Kazatomprom·Argus 요청에 `source_unavailable:okf_body_unavailable`가 기록됐다. r10f 전체 30문항 재실행은 r2 수정 이미지가 준비된 후 진행한다.

## r2·r4·r5 수용 반복

- r2 원시 `/tmp/sol-okf-r2-accept-260922/`: JV Inkai의 45.281·67.536 표를 제시했으나 dense 출처 혼합 가능성이 남아 r2는 최종 후보가 아니다. Escondida는 source_unavailable, 복수 Kazatomprom은 광상 설명을 위치로 읽는 답이 나왔다. Argus 공개 차단과 `mine.rank`는 유지됐다.
- r3는 이후 패치와 이미지가 곧 준비되어 healthz 확인만 하고 질문 요청을 생략했다.
- r4 원시 `/tmp/sol-okf-r4-accept-260922/`: JV Inkai·Escondida 모두 무인용 source_unavailable, 복수 Kazatomprom은 `ambiguous`. 공개 Argus는 기권, 기존 `mine.rank`는 답변했다. r4 수용 핵심은 불합격이다.
- r5 이미지 `sha256:dd5296d4c58c92f824792df3d68e6ac882905a52657b4526ff407328e281fbca`, 18010 `/healthz` 정상. 원시 `/tmp/sol-okf-r5-accept-260922/`. JV Inkai는 `mine.profile` stage3 기권, Escondida는 `document.lookup` stage3 기권, 복수 Kazatomprom은 `ambiguous`, Argus public은 무인용 source_unavailable, `mine.rank`는 답변·집계 인용 1건이다. 로그의 Advisor 사유는 JV Inkai 요청의 근거에 RU-6·Appak·Semizbay-U 행만 있고 **JV Inkai 행이 누락**, Escondida 요청의 근거에 **국가 정보가 누락**됐다는 것이다. r1의 잘못된 Cigar Lake 인용은 막았으나 명시 문서의 목표 본문 행 선택은 아직 실패했다.

두 수용 핵심이 통과하지 않았으므로 r10f 30문항 재실행은 보류했다. 새로운 수정 이미지에서 목표 행 인용과 공개 접근 경계를 먼저 검증한다.

## r6 수용: Escondida 통과, JV Inkai 생성 단계 오판

- 이미지 `sha256:5b3901e28e967838be60a35ea537f8f209fef9be5c619b3e1be7c59c77843707`, 18011 `/healthz` 정상. 원시 `/tmp/sol-okf-r6-accept-260922/`.
- Escondida는 `document.lookup` stage4 응답으로 **칠레**와 실제 OKF 원문 `We are optimising our growth program at Escondida in Chile`를 제시했고 `pageindex` 출처 1건을 인용했다. 본문 값·출처 수용 기준을 충족했다.
- JV Inkai는 `mine.profile` stage4까지 갔지만 최종 `source_not_extracted`와 “이미지·도면 형태라 텍스트 확인 불가”를 반환했다. 그러나 OKF md 32행에는 좌표가 **텍스트 표**로 있다. 이 기권 사유는 실제 원천과 반대라 불합격이다. 복수 Kazatomprom도 source_unavailable이었다.
- Argus public은 무인용 source_unavailable로 차단했고, 기존 `mine.rank`는 집계 인용 1건으로 답했다. 근거 없는 수입액 질문은 unsupported_combination이며 수치를 창작하지 않았다. JV 핵심 실패로 30문항 재실행은 보류한다.

## r6 전체 회귀와 r7 수용

- r6 이미지에서 r10f 보존 JSON의 원문 30건을 `/tmp/r10f_replay_from_json.py`로 재실행했다. 원시 `/tmp/sol-okf-r6-r10f-replay-260922/`. 전부 curl exit=0·SSE done 수신. 답변 8건, `source_unavailable` 21건, Q30 `out_of_scope` 1건. `slot_unresolved`·`unsupported_combination`은 0건. Q23→Q24→Q25 세션 연결, Q15/Q21/Q22 무인용 기권, Q30의 실제 범위 밖 분류를 유지했다. 문항별 기준과 다른 것은 Q06/Q10 `unsupported_combination→source_unavailable`(리튬 가격 기간·현행 진단 정본 부족에 맞는 안전 기권)과 Q12 `source_unavailable→답변`뿐이다. Q12는 니켈 HHI 2327.98을 더미 통관 원천으로 계산하고 본문에 `DEV_DUMMY` 경고를 달았다. 실데이터 답변 성적에는 넣지 않으며 기존 계획 추출 변동/더미 응답 품질 이슈로 기록한다. 나머지 27건은 reason·citation source·표/차트 개수가 기준과 같았다.
- r7 이미지 `sha256:4b3d0e9c5b31ed6d06fa535b7dd7addd16a2f2c9df3f1155421bc929c9a2c7c3`, 18012 `/healthz` 정상. 원시 `/tmp/sol-okf-r7-accept-260922/`. Escondida는 칠레·영문 원문·pageindex 인용 1건으로 다시 통과했다. JV Inkai는 여전히 `mine.profile` stage4에서 `source_not_extracted`와 이미지·도면뿐이라는 거짓 안내를 반환했다. 텍스트 OKF 32행을 보고도 생성 단계가 기권한 것이므로 **불합격**이다. 복수 Kazatomprom은 source_unavailable, Argus public은 무인용 기권, 기존 mine.rank는 인용 1건 답변이다. r7 전체 30건은 변경 범위가 본문 폴백에 집중됐고 r6 전체 회귀가 완료되어 중복 실행하지 않았다.

## r8 수용: 단건 값 통과, 복수 광산·인용 메타 보완 필요

- 이미지 `sha256:105a38fd24e787ee001c01f8f5e5d4915f065068a96d286d26da5d48f4e5294e`, 18013 `/healthz` 정상. 동일 6질문 원시 `/tmp/sol-okf-r8-accept-260922/`.
- JV Inkai는 원문 위치 열의 **45.281, 67.536**을 제시하고 `mine.profile`의 `pageindex` 인용 1건을 붙였다. 헤더에 명시되지 않은 위도·경도 단정은 하지 않았다. Escondida는 **칠레**와 `Escondida in Chile` 영문 원문을 제시하고 `document.lookup`의 `pageindex` 인용 1건을 붙였다. 두 단건의 본문 값과 대상 문서 귀속은 통과한다.
- 인용 `source/source_id`는 실제 OKF path가 아니라 문서 표시 제목이고 `section`은 모두 `명시 문서 본문`, `as_of`는 null이다. 설계의 실제 OKF path·절·기준시점 메타 보존 요구는 아직 미충족이다.
- 복수 Kazatomprom은 source_unavailable로 끝났다. 같은 OKF 28~42행에 여러 광산 위치 행이 있으므로 행별 구별이나 특정 광산 확인 요청이 가능하다. 수용 기준상 **불합격**이다. Argus public은 무인용 source_unavailable로 차단, 기존 mine.rank는 집계 인용 1건 답변을 유지했다. 없는 JV Inkai 수입액 질문은 값을 꾸며내지 않았지만 unsupported_combination으로 분류돼 개선 후보로 남긴다.

## r9 전체 회귀와 r10 최종 수용

- r9 이미지 `sha256:bc66b1d07b53dc58cbfa427f6a7401ebdf0eea74b3b7aab63033f6e6bf43db5e`, 18014 `/healthz` 정상. 수용 원시 `/tmp/sol-okf-r9-accept-260922/`: JV Inkai는 실제 OKF path와 **32행**을 인용해 45.281/67.536을 제시했고, Escondida는 path **33행**을 인용해 칠레와 영문 원문을 제시했다. Argus 공개 문서는 무인용 기권, 기존 mine.rank는 집계 답변. 복수 Kazatomprom은 source_unavailable이라 아직 불합격이었다.
- r9에서 r10f 평가 원문 30건을 재실행했다. 원시 `/tmp/sol-okf-r9-r10f-replay-260922/`. 모두 exit=0·done 수신, 답변 6·source_unavailable 23·Q30 out_of_scope 1, slot_unresolved 0·unsupported_combination 0. Q12 더미 니켈 HHI는 source_unavailable로 올바르게 차단됐고 Q15/Q21/Q22는 무인용 기권. **Q14 실자료 HS 2603000000**이 `trade.hs_summary` stage3 뒤 source_unavailable로 한 차례 기권해 회귀 가능성을 발견했다. Q14는 이후 r10 동일 질문 재요청에서 실자료 답변과 인용으로 복구돼 재현성 이슈로 기록한다.
- r10 이미지 `sha256:84d39853022e628f40d1291c7ae0056e3e8914dc23c2c4270fc71133a56b4629`, 18015 `/healthz` 정상. 동일 수용 원시 `/tmp/sol-okf-r10-accept-260922/`. JV Inkai는 45.281/67.536과 해당 OKF path 32행, Escondida는 칠레와 원문 및 path 33행 인용으로 통과했다. 복수 Kazatomprom은 `ambiguous`로 “여러 광산이 있어 하나의 위치로 답할 수 없다. 광산명을 지정”하라고 안내해 수용 기준을 충족했다. Argus 공개 문서는 인용 없이 source_unavailable, mine.rank는 집계 답변 유지. 근거 없는 JV Inkai 수입액 질문은 unsupported_combination으로 차단됐으며 수치를 창작하지 않았다.
- r10의 추가 Q12·Q14·Q30 원문 재검증은 `/tmp/sol-okf-r10-regression-260922/`: Q12 source_unavailable(더미 차단), Q14 실자료 답변·인용 복구, Q30 날씨·점심 원문에만 out_of_scope. 이번 변경은 단건 OKF 본문 연결과 다수 광산 명확화 경로를 검증한 것이며, 30문항의 모든 답변 내용 정확성을 보증하지 않는다. r9 Q14의 일시 기권과 기존 planner 변동은 별도 재현성 이슈다.
- r10 코드 리뷰에서 일반 PageIndex 본문 폴백에 JV Inkai 값 하드코딩과 문장 등장 횟수 기반 모호성 판정이 남아 있었다. 위 실제 질문 통과만으로 다른 광산·문서에도 안전하게 작동한다고 볼 수 없어, 표 열과 서로 다른 광산명 행을 쓰는 범용 처리로 보완한 r11에서 다시 검증한다.
- Q14의 r9 1회 기권이 반복적인지 좁혀 확인했다. r10에서 동일 원문은 첫 targeted와 추가 2회(`/tmp/sol-okf-r10-q14-repeat-260922/run{1,2}/`) 모두 HS 실자료 답변·인용으로 끝났다(3/3). r9 1회 실패의 재현 원인은 확정하지 못했으므로, r10의 이 확인만으로 장기 안정성을 단정하지 않는다.

## r11 일반화 최종 후보: 수용 통과, Q20 계획 회귀

- 이미지 `sha256:e911cc86df09583ae86f3813ffc517c409e5ed6be5ec46eefd3fbbbb56d63dd1`, 18016 `/healthz` 정상. 수용 원시 `/tmp/sol-okf-r11-accept-260922/`에서 JV Inkai 45.281/67.536와 OKF 32행 인용, Escondida 칠레·영문 원문과 OKF 33행 인용, 복수 Kazatomprom의 광산명 지정 요청, Argus public 무인용 기권, mine.rank 기존 답변을 확인했다. BHP 인용 메타의 `동일 식별자 행`이 r8의 27개에서 1개로 바뀌어 서술 등장 횟수 기반 모호성 판정이 완화됐다.
- 전체 r10f 평가 원문 30건은 `/tmp/sol-okf-r11-r10f-replay-260922/`. 모두 exit=0·done 수신. 답변 7건, source_unavailable 21건, unsupported_combination 1건(Q20), Q30 out_of_scope 1건, **slot_unresolved 0건**. Q12 더미 HHI 차단, Q14 실자료 HS 답변, Q15/Q21/Q22 무인용 기권, Q17 계산식·정적 인용은 유지됐다.
- **Q20은 불합격 회귀**: “전기차 수요가 둔화되면 리튬·니켈·코발트에 어떤 영향이 있을까? 데이터로 확인된 내용과 추론을 구분해줘.”가 r10f에서는 document.retrieve 후 source_unavailable, r6/r9에서는 stage1 source_unavailable였으나 r11에서는 stage1 unsupported_combination이다. SSE에는 추출 계획이 노출되지 않아 과분해인지 모델 변동인지는 아직 확정하지 못했다. 단순 원천 부족 pass로 처리하지 않고 r12에서 재검증한다.

## r12: Q20 해소, Q14 Advisor 오류 재현

- 이미지 `sha256:0e0ed04d5dc052d074535920111cea0d5531c366fd01da22acdf43ded5122369`, 18017 `/healthz` 정상. Q20 동일 원문 3회(`/tmp/sol-okf-r12-q20-repeat-260922/`) 모두 stage1 source_unavailable로 종료해 unsupported_combination이 재발하지 않았다. r11 컨테이너 재추출에서 Q20은 document.retrieve(concept/content)와, 원문에 없는 price.compare(data, 3광종, period=null)의 불필요한 조합이었고 Terra가 이 typed 조합을 보정했다.
- 동일 6개 OKF 수용 질문 원시 `/tmp/sol-okf-r12-accept-260922/`: JV Inkai 값·path 32행 인용, Escondida 국가·원문·path 33행 인용, 복수 광산 명확화, Argus 공개 차단, 기존 mine.rank 답변이 유지됐다. 없는 수입액은 unsupported_combination으로 안전 차단됐다.
- 전체 30문항 원시 `/tmp/sol-okf-r12-r10f-replay-260922/`: exit=0·done 30건, 답변 6·source_unavailable 23·out_of_scope Q30 1, slot_unresolved 0·unsupported_combination 0. **Q14는 stage3 source_unavailable로 재발해 불합격**이다. r12 컨테이너에서 같은 `komis_explicit_hs_import_summary('2603000000')` 도구를 직접 호출하면 수입금액·수입중량 Evidence 2건(2014-01-01~2026-07-01)과 warnings=[]가 정상 반환됐다. 서버 로그의 실제 기권 사유는 `retrieval_verify_invalid_output:LLMOutputError` 및 `advisor_rejected`다. 이는 실자료 부족이 아니라 Advisor 출력 오류를 source_unavailable로 반환한 것이다. r11 성공과 r9/r12 실패의 변동 원인이므로 별도 안정화가 필요하다.

## r13: HS 근거 검증 안정화, JV 계획 변동 확인

- 이미지 `sha256:a8a27a993a8a4238a3b1ad8f0baea0e351036fe789ebd745bfc8979d284738e0`, 18018 `/healthz` 정상. Q14 별도 3회 원시 `/tmp/sol-okf-r13-q14-repeat-260922/run{1,2,3}/`, 전체 30문항 `/tmp/sol-okf-r13-r10f-replay-260922/`. Q14는 3회와 전체 1회 모두 실제 HS 2603000000 수입금액·중량을 동일 `public.KO_CSTM_CMMRC`의 USD·kg 근거 2건으로 답했다. 30건은 답변 7·source_unavailable 22·Q30 out_of_scope 1, slot_unresolved 0·unsupported_combination 0이다.
- 수용 `/tmp/sol-okf-r13-accept-260922/` 첫 JV Inkai는 stage2 `mine.profile` 뒤 stage3 `source_unavailable:okf_body_unavailable`로 기권했다. 같은 질문 재실행은 OKF 32행의 45.281/67.536과 인용으로 성공했다. 컨테이너에서 별도 계획 추출은 `mine_name=JV Inkai`, `topic=Kazatomprom 우라늄 광산 정리자료`였고 그 슬롯의 PageIndex 직접 호출은 목표 본문 1건을 반환했다. 실제 실패 요청의 계획은 SSE에 노출되지 않으나, topic 생략에 따른 문서 선택 변동이 원인으로 좁혀졌다. Escondida, 복수 광산 명확화, Argus 공개 차단, mine.rank는 첫 수용에서 통과했다. 근거 없는 JV 수입액 질문은 첫 실행 `unsupported_combination`, 재실행 `slot_unresolved`로 변동했으나 값은 만들지 않았다. 별도 수용 문항의 슬롯 실패이므로 후속 확인이 필요하다.

## r14: 전체 30 통과, Escondida 계획 변동 1회 잔존

- 이미지 `sha256:7f8521292870770e1a640385ff090ae5bac1a31341b306a2265323212c0c2911`, 18019 `/healthz` 정상. 전체 원시 `/tmp/sol-okf-r14-r10f-replay-260922/`: 30/30 exit=0·done, 답변 7·source_unavailable 22·Q30 out_of_scope 1, **slot_unresolved 0·unsupported_combination 0**. Q23→Q24→Q25 동일 세션에서 Q25는 source_unavailable, 슬롯 실패 없음. Q15/Q21/Q22는 무인용 source_unavailable이며 직접 뒷받침할 문서가 없어 정책상 허용한다. Q30 원문은 서울 날씨·점심 추천으로 실제 범위 밖이다.
- Q14 별도 반복 3/3(`/tmp/sol-okf-r14-q14-repeat-260922/run{1,2,3}/`)과 전체 중 1/1 모두 HS 2603000000의 수입금액(USD)·수입중량(kg)을 같은 원천 `public.KO_CSTM_CMMRC` 인용 2건으로 답했다. r12의 실자료를 Advisor 오류로 기권한 회귀는 이번 반복에서 재발하지 않았다. Q12 더미 HHI는 무인용 source_unavailable, Q17은 실측 수치를 만들지 않고 정적 방법 문서 인용으로 입력값·단위·두 계산식을 제공, Q20은 source_unavailable이다.
- 수용 원시 `/tmp/sol-okf-r14-accept-260922/`: JV Inkai는 45.281/67.536과 정확한 OKF 32행 인용, 복수 Kazatomprom은 광산명 지정 요청, Argus 공개 문서는 무인용 차단, 기존 mine.rank는 집계 인용 답변. JV 동일 질문 추가 3/3도 값과 인용 통과(`/tmp/sol-okf-r14-jv-repeat-260922/`). 근거 없는 수입액 질문은 unsupported_combination으로 수치를 창작하지 않았다.
- **잔여 불합격**: Escondida 수용 첫 1회는 stage1 `unsupported_combination`으로 기권했다. 같은 원문 API 재실행 3/3은 칠레와 `Escondida in Chile` 원문을 실제 OKF 33행 인용으로 답했다(`/tmp/sol-okf-r14-escondida-repeat-260922/`). 컨테이너에서 별도 추출한 계획은 단일 `document.lookup`이었으므로 모델 계획 출력의 일시적 중복 분해 가능성이 있으나 실패 요청의 정확한 계획은 확인되지 않았다. 실본문이 있으므로 첫 기권을 `source_unavailable` 허용이나 수용 통과로 처리하지 않는다. 후속 계획 안정화와 재검증이 필요하다.
- Q01·Q07·Q23의 기존 가격 데모 응답은 이번 OKF 변경 범위의 수용 성적에 합산하지 않았다. 실제 통계 답변 여부는 `DEV_DUMMY` 및 관측기간을 따로 검증해야 하며, Q12의 더미 HHI는 이번 이미지에서 차단됐다.

## r15: Escondida 회귀 해소, 근거 없는 수입액 질문의 슬롯 오류 발견

- 이미지 `sha256:37f8da156c55f2be388557070c6692c15e04be71d6937f1d221dff4c0eefb897`, 18020 `/healthz` 정상. 수용 `/tmp/sol-okf-r15-accept-260922/`와 반복 `/tmp/sol-okf-r15-repeat-260922/`: JV Inkai·Escondida는 각 4/4에서 실제 OKF 32·33행의 위치 값과 영문 원문을 맞는 path로 인용했다. 복수 Kazatomprom은 광산명 지정 요청, Argus public은 무인용 차단, 기존 mine.rank는 집계 인용 답변이다. Escondida의 r14 첫 stage1 실패는 이번 4회에서는 재발하지 않았다.
- Q14 별도 3/3(`/tmp/sol-okf-r15-q14-repeat-260922/run{1,2,3}/`)과 전체 1/1에서 같은 HS 수입금액 USD·중량 kg의 structured 인용 2건으로 답했다. 전체 30 원시 `/tmp/sol-okf-r15-r10f-replay-260922/`: 답변 7·source_unavailable 22·Q30 out_of_scope 1, **Q01~Q30의 slot_unresolved·unsupported_combination은 0**. Q23→Q24→Q25 같은 세션도 슬롯 오류 없이 근거 부족을 분류했다. Q12 더미 HHI 무인용 차단, Q15/Q21/Q22 직접 근거 부족 무인용 기권, Q17 계산 방법만 인용, Q20 source_unavailable 유지.
- **수용 반례 NO_FACT 불합격**: “Kazatomprom 우라늄 광산 정리자료에서 JV Inkai의 2026년 9월 수입액은 얼마야?”는 수용+반복 4회 중 3회 `slot_unresolved`, 1회 `unsupported_combination`이었다. 원문에는 광산명·월·수입액이 명시돼 있으므로 슬롯 미해결로 끝내서는 안 된다. 값·인용은 만들지 않았지만 사용자의 슬롯 0 필수 기준을 위반한다. r15 컨테이너에서 동일 문장 계획을 별도 5회 재추출하면 3회는 `document.lookup` + `trade.monthly`로 분해했고 명시된 2026년 9월을 `future_horizon` 25·1·24개월로 오파싱했다. 1회는 첫 LLM 출력의 `future_horizon=0` 검증 오류 후 repair, 2회는 document.lookup 단일이었다. 실패 API 요청의 정확한 계획은 SSE에 없으므로 직접 재추출은 변동 원인에 대한 근거이며 그 요청의 출력 확정은 아니다. 근거 없는 문서 수입액을 실수치로 답할 수 없다는 결론과 슬롯 실패 여부는 별도로 판정한다.

## r16 최종 격리 검증: 수용 통과

- 이미지 `sha256:91457daf43306a7671f814dd4312a653a3aa4b5e961dc6e5fddbe2b2fbbef76c`, 18021 `/healthz` 정상. 수용 6건 원시 `/tmp/sol-okf-r16-accept-260922/`, JV·Escondida 각 추가 3회와 NO_FACT 추가 6회 원시 `/tmp/sol-okf-r16-repeat-260922/`.
- JV Inkai 4/4는 OKF 문서 **32행**의 위치 열 45.281/67.536을 해당 path 인용 1건으로 답했다. 원문에 없는 위도·경도 레이블은 단정하지 않았다. Escondida 4/4는 OKF **33행**의 `Escondida in Chile`로 칠레와 영어 원문을 해당 path 인용 1건으로 답했다. 복수 Kazatomprom은 `ambiguous`로 광산명 지정을 요청했다. Argus public은 `source_unavailable`·인용 0으로 제한 문서 접근을 막았고, 기존 mine.rank는 집계 인용 1건으로 답했다.
- **NO_FACT 7/7**은 `document.lookup`을 실행한 뒤 `source_unavailable`·인용 0으로 끝났고 `slot_unresolved`는 없다. 실제 `20260813_Kazatomprom_우라늄_광산_정리자료.md`에서 `수입액|수입금액|2026년 9월|2026-09|JV Inkai`를 대조하면 JV 위치 표 32행만 일치하고 요청한 월별 수입액 행은 없다. 따라서 이번 출처 부족 기권은 원천 부재에 부합한다. 광산별 월 수입액을 전체 통관 집계로 대체하지 않았다.
- Q14 별도 3/3 원시 `/tmp/sol-okf-r16-q14-repeat-260922/run{1,2,3}/`와 전체 중 1/1은 같은 `public.KO_CSTM_CMMRC`의 HS 2603000000 수입금액 USD·수입중량 kg 근거 2건으로 답했다. r12의 Advisor 출력 오류로 인한 거짓 기권은 이번 네 요청에서 재발하지 않았다.
- 기준 30문항 전체 원시 `/tmp/sol-okf-r16-r10f-replay-260922/`: 30/30 exit=0·done, 답변 7·source_unavailable 22·Q30 out_of_scope 1, **slot_unresolved 0·unsupported_combination 0**. Q23→Q24→Q25 동일 세션에서 후속 슬롯 실패 없이 출처 부족을 분류했다. Q12 DEV_DUMMY HHI는 무인용 기권, Q15/Q21/Q22는 직접 근거 부족에 따른 무인용 기권, Q17은 실수치 없이 인용된 입력값·계산식 답변, Q20은 source_unavailable이다. Q30의 서울 날씨·점심 메뉴 질문은 실제 광물 서비스 범위 밖이다.
- 판정: **이번 PageIndex·OKF 단건 조회 변경과 r9 슬롯 기준을 r16 격리 컨테이너에서 수용**한다. `source_unavailable`은 NO_FACT처럼 실제 문서에 요구 사실이 없거나 기존 검증에서 해당 실원천이 없는 경우에만 통과로 집계했다. Q01·Q07·Q23의 기존 가격 데모/관측기간 품질은 이 수용 범위 밖의 별도 이슈이며 실통계 성공으로 집계하지 않는다. 반복 횟수는 유한하므로 LLM 계획의 모든 변동을 배제하는 증명은 아니다. 이 결과는 18021 격리 이미지의 실요청 관찰이며 운영 컨테이너에는 배포하지 않았다.

## 운영 추가 반례와 r17 격리 검증: 증가 순위 회귀

- r16 운영 추가 점검 원시 `/tmp/komir-r16-postdeploy-260922/CHINA_TOP.{json,sse}`: “중국의 생산량이 가장 많은 광산이 어디 있나요? 이름이 뭔가요?”가 stage1 `slot_unresolved`였다. 운영 이미지에서 같은 원문의 계획을 3회 직접 추출하면 모두 완결된 `mine.rank`(production, level, top_n=1, country_scope=중국) 뒤에 `mine_name=None`인 `mine.profile`을 불필요하게 추가했다. 후자의 필수 슬롯 누락이 원인이다. 광종 미지정은 `mine.rank`의 필수 슬롯이 아니며, 집계기는 광종 미지정 시 6개 폴더를 순회한다.
- r17 이미지 `sha256:ee5937e361ebf67acf3e60a3593cc48762b42c29a13e7380ced3e5d0933ef6fb`, 18023 `/healthz` 정상. 원시 `/tmp/komir-r17-predeploy-260922/`. CHINA_TOP은 `mine.rank` 단일 액션으로 광산 문서 99건을 조회한 뒤 `source_unavailable`·인용 0으로 기권했다. 슬롯 오류는 해소됐다. 컨테이너 로그의 원인은 `source_unavailable:mine_no_comparable_values:all`; 중국 광산의 비교 가능한 생산량 근거가 없어 나라·광산명을 지어내지 않은 것으로 판정한다. 서로 다른 광종의 생산량 단위와 basis를 확인하지 않고 세계 전체 1위를 단정해서도 안 된다.
- **r17은 최종 수용 불가**: 같은 원문 “최근 3년 이내 생산량 증가가 많은 광산 상위 5개를 알려주세요.”가 `mine.rank`로 99문서를 조회하고 stage3 `source_unavailable`·인용 0으로 끝났다. 운영 r16의 같은 원문(`/tmp/komir-r16-postdeploy-260922/MINE_INCREASE.json`)은 2024→2025의 5개 광산 증가량을 실제 집계 인용 1건으로 답했다. r17 로그는 `mine_metric_extract` JSON 파싱 재시도 뒤 Advisor가 “Escondida 1곳만 포함”이라고 거부했다. 따라서 실자료가 있던 질문의 이번 기권은 출처 부족 pass가 아니며 집계·근거 추출 회귀로 기록한다.
- r17의 JV Inkai·Escondida·복수 광산·NO_FACT·Argus public·기존 mine.rank·HS_SUMMARY는 기대 응답/기권을 유지했고 Q20은 직접 근거 부족으로 기권했다. 다만 증가 순위 회귀가 남아 r17을 배포 승인하지 않는다.

## r18 중간 판정: 증가 순위의 원문 연도 오독

- r18 이미지 `sha256:1e25f36e8ec1ed6b4cabd2d7c8e7bdb1831b458ac149b647c2af8b64151144cf`, 18024 `/healthz` 정상. 원시 `/tmp/komir-r18-predeploy-260922/`. `MINE_INCREASE`는 5행 집계 답변을 냈으나 수치·연도 검증에서 **불합격**이다.
- 인용 대상 `광산자료/동_구리/Cu_Oyu_Tolgoi_Rio_Tinto.md:891-918`의 표 헤더는 `Q4 2024`, `Q1 2025`, `Q2 2025`, `Q3 2025`, `Q4 2025`, **연간 2024**, **연간 2025**다. r18 답변의 Oyu Tolgoi `2024 43,800→2025 141,900`은 실제로 **Q4 2024 43.8천t→연간 2024 141.9천t**을 서로 다른 연도로 오독한 것이다. Bingham Canyon `2024 31,200→2025 123,400`도 Q4 2024→연간 2024의 혼합이다. 올바른 Oyu 연간 2024→2025 비교는 141.9천t→227.8천t, 증가 85.9천t이다. r16 운영 답변도 Oyu 43.8천t(Q4 2024)→227.8천t(연간 2025)을 2개 연간값으로 혼합했다. r18 결정적 Advisor 우회는 추출 표 자체의 기간 오류를 검출하지 못했다.
- 따라서 현재 5행 중 최소 두 행의 시작·끝연도와 증가량이 거짓이며, r18의 정량 답변을 수용하거나 운영 배포할 수 없다. 남은 수용 질문은 원시 결과 보존 목적으로만 실행하고, 원문 헤더와 값의 정합성이 보장된 후 재검증한다.
- 나머지 r18 실요청도 완료했다. CHINA_TOP은 `mine.rank`에서 `source_unavailable`·인용 0·슬롯 0이며 로그 원인은 `source_unavailable:mine_no_comparable_values:all`이다. JV Inkai·Escondida는 각각 OKF 32·33행 인용, 복수 Kazatomprom은 명확화, NO_FACT·Argus public은 무인용 출처 부족, 기존 리튬 매장량 mine.rank와 HS 수입금액·중량은 인용 답변, Q20은 무인용 기권으로 기존 경계를 유지했다. 이 성공 항목들이 증가 순위의 허위 연도 행을 상쇄하지 않는다.

## r19·r20: 연간 행 원문 대조와 Advisor 변동

- r19 이미지 `sha256:7b47e5510f3980fbe15232efbfb57d35e6ee6b67e5dea16d750252cb91213849`, 18025 원시 `/tmp/komir-r19-predeploy-260922/`. API `MINE_INCREASE`는 99문서 조회 뒤 source_unavailable였고 로그 Advisor는 Escondida 1개만 있다고 판단했다. 그러나 같은 r19 컨테이너에서 `aggregate_mine_metric('', '생산량', 'rank', since_year=2024, order='increase', top_n=5)` 직접 호출은 warnings=[]와 **5행 집계 Evidence 1건**을 반환했다. API의 기권은 실제 집계 표와 어긋나므로 실데이터 부족 pass가 아니다.
- 직접 집계 5행의 원문 대조: Escondida `Cu_Escondida_Pampa_Norte_BHP.md:415-421` FY24 1,125kt→FY25 1,305kt(+180kt); Tenke Fungurume `Cu_Kisanfu_CMOC.md:2745` 2024 409,410t→2025 519,361t(+109,951t); SALVADOR·RADOMIRO TOMIC `Cu_El_Teniente_Radomiro_Tomic_Chuquicamata_Andina_Codelco.md:132-140` FY24→FY25R 5.7→47.0kt(+41.3kt), 270.5→295.3kt(+24.8kt); Highland Valley Copper `Cu_Antamina_Quebrada_blaco_Teck_2025-Annual-Report.md:420-422` 102,400→127,100t(+24,700t). Rio의 Q4/연간 혼합 값은 5행에서 제외됐다.
- r20 이미지 `sha256:d21f3122c28ca0b781a1e81534c890b4077f483c83c78770abdc4468ea286370`, 18026 원시 `/tmp/komir-r20-predeploy-260922/`. `MINE_INCREASE` API는 위 5행의 순위·증가량과 집계 인용 1건을 답했다. SSE table `rows_typed`에는 각 광산의 2024/2025 시작·끝 값, t 단위 `metal` basis, 개별 OKF path가 있어 원문 대조에 통과했다. CHINA_TOP은 `mine.rank` 후 무인용 source_unavailable, 슬롯 0. 다만 r19의 Advisor 오독 변동을 막는 결정적 검증 경로는 r20 이미지에 없으므로 r21에서 반복 검증한다.

## r21 최종 격리 수용

- 이미지 `sha256:0caea6e44b2c3389a7318010547e9725522e7aed6f89c99fd89a7f4129bcdd5e`, 18027 `/healthz` 정상. 수용 원시 `/tmp/komir-r21-predeploy-260922/`. `MINE_INCREASE_1`·`MINE_INCREASE_2`는 모두 답변·aggregated 인용 1건이며 `tables[0].rows_typed`가 **완전히 같다**. 2024→2025 연간 `metal` 생산량 t 기준 5행은 Escondida +180,000, Tenke Fungurume +109,951, SALVADOR +41,300, RADOMIRO TOMIC +24,800, Highland Valley Copper +24,700이다. 각 시작·끝 값과 출처는 위 BHP·CMOC·Codelco·Teck 원문 행에 일치하고, Rio의 분기/연간 혼합 행은 없다. 반복은 유한하므로 모든 LLM·원천 변동에 대한 보증은 아니다.
- CHINA_TOP은 `mine.rank` 단계2·3 뒤 `source_unavailable`·인용 0으로 끝나 **slot_unresolved 0**이다. 기존 r17/r18의 직접 로그에서 이 경로는 `mine_no_comparable_values:all`이었고, 중국 소재 광산의 비교 가능한 생산량이 없을 때 광산명을 창작하지 않았다. JV Inkai는 OKF 32행의 45.281/67.536 인용, Escondida는 OKF 33행의 칠레·영어 원문 인용, 복수 Kazatomprom은 광산명 지정 요청, NO_FACT·Argus public은 무인용 기권, 리튬 매장량 mine.rank는 기존 집계 답변, HS 2603000000은 USD 수입금액·kg 수입중량 2인용 답변, Q20은 무인용 기권을 유지했다.
- r10f 원문 전체 30건 원시 `/tmp/sol-okf-r21-r10f-replay-260922/`: **30/30 exit=0·done, 답변 7·source_unavailable 22·Q30 out_of_scope 1, slot_unresolved 0·unsupported_combination 0**. Q23→Q24→Q25 동일 세션에서 Q25는 실근거 부족으로 기권했고 슬롯 오류가 없다. Q14 실자료 2인용 답변, Q12 DEV_DUMMY HHI 무인용 차단, Q17 계산 정의만 정적 출처 인용, Q15/Q21/Q22 직접 근거 부족 무인용 기권을 유지했다. Q30의 서울 날씨·점심 추천은 질문 자체가 서비스 범위 밖이다.
- **판정: r21 격리 이미지의 이번 변경 수용.** r17의 중국 광산 슬롯 오류와 r18의 분기·연간 혼합 허위 증가량, r19의 5행 근거 오독은 재검증 요청에서 재발하지 않았다. `source_unavailable`은 요구한 실제 원천이 없는 경우에만 통과로 분류했고, 실원천이 있는데 잘못 기권했던 증가 순위는 답변·원문 대조로 해결됐다. 결과는 18027 격리 API 기준이며 운영 재배포 결과는 별도 점검해야 한다.

## r21 운영 18002 배포 후 독립 점검

- 운영 `komir-rag-chat-test`의 `docker inspect .Image`는 `sha256:0caea6e44b2c3389a7318010547e9725522e7aed6f89c99fd89a7f4129bcdd5e`로, 격리 검증 r21 이미지와 같다. 운영 실요청 10건 원시 `/tmp/komir-r21-postdeploy-260922/*.json` 및 `.sse`: 10/10 exit=0·done, `slot_unresolved` 0. 이 점검에서 코드·컨테이너를 변경하지 않았다.
- `MINE_INCREASE`는 `mine.rank`로 5행·집계 인용 1건을 답했다. SSE `rows_typed`의 각 행을 OKF 원문과 다시 대조했다: Escondida BHP 문서 415~421행 **FY24 1,125,000→FY25 1,305,000t, +180,000t**; Tenke CMOC 2745행 **409,410→519,361t, +109,951t**; SALVADOR·RADOMIRO TOMIC Codelco 132~140행 **5,700→47,000t, +41,300t** 및 **270,500→295,300t, +24,800t**; Highland Valley Copper Teck 420~422행 **102,400→127,100t, +24,700t**. 다섯 행 모두 2024→2025 연간 `metal`·t와 증가량 산식이 맞고 Rio 분기/연간 혼합 행은 없다. Escondida의 국가 열은 운영 응답에서 `-`로 빠졌지만 질문의 생산량 순위 수치와 출처 귀속은 유지됐다.
- `CHINA_TOP`은 stage2/3 `mine.rank` 뒤 `source_unavailable`·인용 0·슬롯 오류 0으로 종료했다. r17/r18 직접 로그의 `mine_no_comparable_values:all`과 일관되며, 중국 광산의 비교 가능한 생산량 근거가 없을 때 이름을 창작하지 않았다.
- `HS_SUMMARY`는 HS 2603000000 수입금액 **58,890,426,933 USD**·수입중량 **23,089,277,377 kg**을 동일 `public.KO_CSTM_CMMRC`의 2014-01-01~2026-07-01 원천 인용 2건으로 답했고 광종 전체 합계와 구분했다. JV Inkai는 OKF Kazatomprom 문서 32행 45.281/67.536, Escondida는 BHP 문서 33행 칠레·영어 원문을 각각 올바른 `pageindex` 인용 1건으로 답했다.
- 복수 Kazatomprom은 `ambiguous`로 광산명 지정을 요청, 없는 JV 월 수입액·Argus public은 무인용 `source_unavailable`, 기존 리튬 매장량 mine.rank는 집계 인용 답변, Q20은 직접 출처 부족으로 무인용 기권했다. **운영 10건은 이번 수용 기준에 통과**한다. 이는 유한한 실요청 점검이며 r21 격리 30건 전체 재실행 결과와 함께 해석한다.
