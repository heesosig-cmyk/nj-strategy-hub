# NJ STRATEGY HUB — 클라우드 공고수집 1차 구현

## 구현 범위
- GitHub Actions 스케줄: UTC 00:17, 06:17, 12:17 (한국시간 09:17, 15:17, 21:17)
- 조달청 나라장터 **용역 입찰공고** API(신규 BidPublicInfoService02) 조회
- 최근 2일 조회(공식 최대 7일 제한 준수), 키워드 필터, 중복 식별, 변경 여부 표시
- `docs/notices.json` 공개 피드 생성; NJ STRATEGY HUB v7.5에서 URL로 피드 조회, 사용자 승인 후 연구과제 등록
- 개인 연구과제 기록은 기존 브라우저 localStorage에 유지. 공개 GitHub에 업로드하지 않음

## 설치 순서
1. https://www.data.go.kr/data/15129394/openapi.do 에서 활용신청하고 **일반 인증키(Decoding)** 를 발급받습니다.
2. 개인 GitHub 저장소를 **새로 생성**합니다. 이 패키지 파일을 업로드합니다. 저장소는 공개 피드만 포함하므로 **개인 백업 JSON 파일은 절대 업로드하지 마십시오.**
3. GitHub 저장소 Settings → Secrets and variables → Actions → New repository secret에 이름 `DATA_GO_KR_SERVICE_KEY` 로 키를 등록합니다. 키를 HTML 파일에 넣지 마십시오.
4. Actions 탭에서 `Collect public procurement notices` → `Run workflow`로 수동 테스트합니다. API 응답·인증 문제가 있으면 Actions 로그를 확인합니다.
5. Settings → Pages → Deploy from a branch → `main` / `docs` 를 선택합니다. 공개 피드 URL은 `https://<GitHub사용자명>.github.io/<저장소명>/notices.json` 형태입니다.
6. NJ STRATEGY HUB v7.5 HTML을 실행 → `공고 수집센터` 메뉴 → 공개 피드 URL 입력 → `공고 가져오기` 클릭 → 검토 후 `연구과제 등록` 버튼을 사용합니다.

## 한계 및 주의
- GitHub 저장소/Pages 배포는 아직 수행되지 않았습니다. 실제 API 인증키가 없어 실 API 호출은 미검증입니다.
- 공식 API는 공고 **조회** 용도입니다. 입찰자격 적격 여부를 자동 확정하지 않습니다.
- API 오류 시 피드를 덮어쓰지 않도록 설계했습니다. GitHub Actions 실패 알림을 확인하세요.
- `docs/notices.json`은 공개됩니다. 개인 연구자료, 평가점수, 협력기관 정보는 저장하지 않습니다.
- 나라장터 외 D2B, IRIS 등은 공식 상세 오퍼레이션·이용조건 확인 후 별도 어댑터를 추가해야 합니다.
- 공개 API 필드의 예산·마감일은 실제 공고 원문과 반드시 대조하세요.
- GitHub Actions 예약 실행은 지연될 수 있으며 실시간 감시가 아닙니다.

공식 출처: https://www.data.go.kr/data/15129394/openapi.do
