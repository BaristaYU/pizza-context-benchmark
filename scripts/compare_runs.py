"""Build comparison artifacts from existing summary files without API calls."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path: sys.path.insert(0, str(REPO))
from pizzabench.comparison import compare_summaries, render_comparison


def main(argv=None):
    parser = argparse.ArgumentParser(description='Compare real saved batch summaries; no API calls')
    parser.add_argument('runs', nargs='+', type=Path, help='Run directory or summary.json path')
    parser.add_argument('--output-dir', type=Path, default=REPO/'results'/datetime.now().strftime('comparison_%Y%m%d_%H%M%S'))
    options = parser.parse_args(argv)
    output = options.output_dir.resolve()
    try:
        summaries = []
        for source in options.runs:
            source = source.resolve()
            summary_path = source if source.is_file() else source/'summary.json'
            summary = json.loads(summary_path.read_text(encoding='utf-8'))
            summary['source_directory'] = str(summary_path.parent)
            try:
                relative = os.path.relpath(summary_path.parent/'report.html', output).replace('\\', '/')
                summary['report_href'] = quote(relative, safe='/.-_')
            except ValueError:
                summary['report_href'] = (summary_path.parent/'report.html').as_uri()
            summaries.append(summary)
        comparison = compare_summaries(summaries)
        output.mkdir(parents=True, exist_ok=False)
        (output/'comparison.json').write_text(json.dumps(comparison, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        (output/'report.html').write_text(render_comparison(comparison), encoding='utf-8')
    except (OSError, ValueError, KeyError, TypeError):
        print('비교 자료 형식·파일 위치 또는 결과 폴더를 확인하세요. 기존 결과 폴더는 덮어쓰지 않습니다.', file=sys.stderr)
        return 2
    print('COMPARISON '+str(output/'report.html'))
    for warning in comparison['warnings']:
        print('안내: '+warning)
    return 0


if __name__ == '__main__': raise SystemExit(main())
