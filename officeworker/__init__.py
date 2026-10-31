"""コマンド出力の文字コード制限で業務処理を中断しない。"""
import sys

# Windowsのパイプ・定時実行等で出力先が日本語を扱えない場合だけエスケープする。
# 既存の文字コードは変えず、日本語を表示できるコンソールではそのまま表示する。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="backslashreplace")
