# Vision Action Platform

## 로컬 Compose 실행

Docker 엔진과 Compose를 사용할 수 있는 WSL의 프로젝트 루트에서 실행한다.
`ai_service/models/`에는 1단계에서 검증한 Joblib·Feature 목록·학습정보와 YOLO 가중치가 있어야 한다. 모델 폴더는 FastAPI에 읽기 전용으로 연결한다.

1. `.env.example`을 `.env`로 복사하고 `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`에 각자 생성한 값을 입력한다. 이미 `.env`가 있으면 현재 파일에서 필요한 항목만 확인한다.
2. 다음 명령으로 서비스 5개를 실행한다. Django가 PostgreSQL에 기본 마이그레이션을 적용한다.

   ```bash
   docker compose config --quiet
   docker compose up --build -d
   docker compose ps
   ```

3. 브라우저에서 `http://127.0.0.1:8012/`를 열고 회원가입 → 로그인 → MP4 선택 → AI 분석 시작 순서로 진행한다. 작업 번호와 상태가 먼저 표시되고, 완료 후 저장된 결과가 나타난다. 다른 포트를 쓰려면 `.env`의 `VISION_HTTP_PORT`를 바꾼다.
4. 관리자 계정이 필요하면 `docker compose exec django python manage.py createsuperuser`를 실행한다. 로그는 `docker compose logs django celery fastapi`에서 확인한다.
5. 개발용 서비스를 종료할 때는 `docker compose down`을 사용한다. DB·업로드·큐 볼륨은 이 명령으로 유지된다.

Django만 호스트 루프백에 공개한다. Django·Celery는 업로드 볼륨을 공유한다. Django는 Redis에 작업 번호를 보내고, Worker는 `http://fastapi:8001/predict/video`를 호출한다. PostgreSQL은 Django ORM이 관리한다. 기존 3단계 로컬 시연이 필요하면 별도 개발 환경에서 `ANALYSIS_MODE=sync`로 실행할 수 있다.

## 상태와 실패

- 작업 번호의 조회는 기존 본인 전용 `GET /api/analyses/<id>/`를 사용한다.
- 작업 완료는 분석과 저장이 끝났다는 뜻이다. `UNKNOWN`은 낮은 신뢰도 또는 관절 부족일 수 있다.
- 브로커 등록 실패와 일반적인 HTTP 오류·타임아웃은 작업 실패로 기록한다. 프로세스 강제 종료나 시스템 장애 뒤 `STARTED` 작업을 복구하는 절차는 아직 없다.

이 Compose는 로컬 실습용이다. 모델, 원본 영상, 개인 업로드, 로컬 환경, 비밀값 파일은 빌드 이미지와 Git에서 제외한다.