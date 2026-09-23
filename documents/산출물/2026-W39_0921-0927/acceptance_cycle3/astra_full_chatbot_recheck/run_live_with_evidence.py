"""고정 수락 실행기의 판정은 유지하고 감사용 SSE 원본만 별도 보존한다."""
from pathlib import Path
from datetime import datetime, timezone
import json
import sys
import time
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
sys.path[:0] = [str(ROOT / "inhouse"), str(ROOT / "inhouse/rag_chat")]
from rag_chat.tests import run_acceptance_suite as runner

raw = HERE / "live_raw"
raw.mkdir(exist_ok=True)
active = {"id": "unknown", "turn": 0}
original_run = runner.run_case


def ask(base_url, question, session_id, timeout):
    active["turn"] += 1
    prefix = raw / f"{active['id']}_turn{active['turn']}"
    payload = {"user_id": "acceptance-suite", "session_id": session_id, "message": question}
    prefix.with_suffix(".request.json").write_text(json.dumps({
        "body": payload, "url": base_url + "/pubchat", "timeout_seconds": timeout,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2))
    request = urllib.request.Request(base_url + "/pubchat", json.dumps(payload).encode("utf-8"),
                                     {"Content-Type": "application/json"}, method="POST")
    started = time.monotonic()
    try:
        data = bytearray()
        with prefix.with_suffix(".sse").open("wb") as capture:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                while True:
                    line = response.readline()
                    if not line:
                        break
                    capture.write(line)
                    capture.flush()
                    data.extend(line)
                    if time.monotonic() - started > timeout:
                        raise TimeoutError(f"case deadline exceeded {timeout}s")
        events = runner.parse_sse(bytes(data))
        prefix.with_suffix(".events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2))
        return events
    except Exception as exc:
        prefix.with_suffix(".error.json").write_text(json.dumps({
            "type": type(exc).__name__, "error": str(exc),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }, ensure_ascii=False, indent=2))
        raise


def run_case(case, args):
    active.update(id=case["id"], turn=0)
    print("START", case["id"], case["question"], flush=True)
    result = original_run(case, args)
    print("DONE", result["id"], result["status"], result["elapsed_seconds"],
          json.dumps(result["errors"], ensure_ascii=False), flush=True)
    return result


runner.ask_live = ask
runner.run_case = run_case
sys.argv = [str(runner.__file__), "--layer", "live", "--base-url", "http://127.0.0.1:18002",
            "--timeout", "180", "--report-dir", str(HERE / "live")]
raise SystemExit(runner.main())
