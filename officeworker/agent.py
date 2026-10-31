"""受託案件の「工場」: jobs/<案件>/spec.md を自律コーディングエージェントに渡して実装〜動作確認まで回す。
エンジン（CODING_AGENT または --engine）:
  openhands … vendor/openhands-sdk（OpenHands Software Agent SDK, MIT）を Python から直接駆動。Gemini で動く
  claude    … Claude Code CLI（claude -p）
  opencode  … opencode CLI（opencode run）
"""
import os
import shutil
import subprocess
from pathlib import Path

TASK = """あなたは日本の業務自動化ツールを納品するエンジニアです。このフォルダが作業場所です。
1. spec.md を読み、依頼内容を実装する（Python なら main.py。GAS 希望なら code.gs）
2. 親リポジトリの部品が使える: officeworker.io.read_any/write_any（文字コード自動）, officeworker.pdf.invoice/tables,
   officeworker.sheets.push, officeworker.notify.send。ただし exe 納品する場合は main.py 単体で動くようにする
3. in/ のサンプルで実際に実行し、out/ に期待通りの結果が出るまで修正する（サンプルが無ければ spec に沿って作る）
4. README_納品.md を案件内容に合わせて書き換える（使い方・設定項目・よくある質問）
5. 最後に、やったこと・未確認の点を DONE.md に箇条書きで残す
{extra}"""


def detect():
    want = os.getenv("CODING_AGENT")
    if want:
        return want
    for name in ("claude", "opencode"):
        if shutil.which(name):
            return name
    return "openhands"


def run(job_dir: str, engine: str | None = None, extra: str = ""):
    job = Path(job_dir).resolve()
    if not (job / "spec.md").exists():
        raise SystemExit(f"{job}/spec.md がありません（python -m officeworker new 案件名 で作成）")
    task = TASK.format(extra=extra)
    engine = engine or detect()
    print(f"▶ {engine} で実装開始: {job}")
    if engine == "claude":
        subprocess.run([shutil.which("claude") or "claude", "-p", task, "--permission-mode", "acceptEdits",
                        "--allowedTools", "Bash", "Read", "Edit", "Write", "Glob", "Grep"], cwd=job, check=False)
    elif engine == "opencode":
        subprocess.run([shutil.which("opencode") or "opencode", "run", task], cwd=job, check=False)
    elif engine == "openhands":
        _openhands(job, task)
    else:
        raise SystemExit(f"unknown engine: {engine}")
    done = job / "DONE.md"
    print(done.read_text(encoding="utf-8") if done.exists() else "（DONE.md なし）")


def _openhands(job: Path, task: str):
    try:
        from openhands.sdk import LLM, Conversation
        from openhands.tools.preset.default import get_default_agent
    except ImportError:
        raise SystemExit("OpenHands 未導入: pip install -r requirements-agent.txt")
    model = os.getenv("OPENHANDS_MODEL") or f"gemini/{os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')}"
    key = os.getenv("OPENHANDS_API_KEY") or os.getenv("GEMINI_API_KEY")
    llm = LLM(model=model, api_key=key, usage_id="agent")
    agent = get_default_agent(llm=llm, cli_mode=True)  # ターミナル + ファイル編集 + タスク管理
    conv = Conversation(agent=agent, workspace=str(job), max_iteration_per_run=int(os.getenv("OPENHANDS_MAX_STEPS", "80")))
    conv.send_message(task)
    conv.run()
