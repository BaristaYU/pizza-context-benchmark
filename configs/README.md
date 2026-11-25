# API 키와 모델 설정

## 키 파일

`api_keys.example.json`을 같은 폴더에 `api_keys.local.json`으로 복사하고, 사용할 서비스의 빈 따옴표에 발급받은 키를 넣는다. 쓰지 않는 서비스는 빈 문자열로 둔다. `api_keys.local.json`은 Git에서 제외된다.

| 항목 | 발급처 |
| --- | --- |
| `GEMINI_API_KEY` | Google AI Studio |
| `OPENAI_API_KEY` | OpenAI API 플랫폼 |
| `ANTHROPIC_API_KEY` | Claude Console |
| `MISTRAL_API_KEY` | Mistral Studio(무료 티어로 실행 가능) |
| `VLLM_API_KEY` | 직접 띄운 vLLM 서버에 키를 걸었을 때만 입력 |

같은 이름의 환경변수가 있으면 파일보다 먼저 쓴다. 다른 위치의 키 파일은 GUI와 CLI의 `--api-keys`로 지정한다. 키를 공유 파일, 스크린샷, 채팅에 넣지 않는다.

## 모델과 가격

`agent_models.json`에 서비스별 기본 모델, 비용 추정에 쓰는 가격표, vLLM으로 띄울 로컬 모델의 권장 설정이 있다. 서비스에서 실제로 쓸 수 있는 모델 목록은 GUI의 `목록` 버튼이나 `python -m pizzabench.game_cli --list-models --ai-provider <서비스>`로 확인한다. 가격표에 없는 모델은 비용을 추정하지 않고 사용량만 기록한다. 실행 방법과 서비스 간 공정 비교 조건은 [모델 실행](../docs/model_runs.md)에 있다.
