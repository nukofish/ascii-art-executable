"""Real-A eligibility and extraction boundary regression tests."""
from codeart.prepass import inspect_file, selected_source


def test_prepass_honors_caller_cancellation():
    from threading import Event
    from time import monotonic
    import pytest
    from codeart.contracts import ErrorCode, RunContext, StageError

    cancelled = Event()
    cancelled.set()
    with pytest.raises(StageError) as failure:
        inspect_file("int f(void){return 0;}", ctx=RunContext(monotonic() + 30, cancelled))
    assert failure.value.diagnostic.code == ErrorCode.CANCELLED


def test_real_dependencies_and_original_lines():
    text = '#include <stdio.h>\nint g=1;\nint bad(void){return g;}\nint good(int x){return x+1;}\nint main(void){return 0;}\n'
    result = inspect_file(text)
    assert [(c.name, c.a_status) for c in result.candidates] == [('bad', 'FAIL'), ('good', 'PASS'), ('main', 'FAIL')]
    assert result.candidates[0].diagnostic['line'] == 3
    assert result.selected == 'good'
    assert selected_source(result) == 'int good(int x){return x+1;}'
    assert result.ignored_lines == [dict(start_line=1, end_line=3, reason='Outside the selected function'), dict(start_line=5, end_line=5, reason='Outside the selected function')]


def test_literals_comments_prototypes_and_selection():
    text = 'int proto(int x);\n/* } 中文 */\nint first(int x){ /* { */ return x;}\nint second(void){return 2;}'
    result = inspect_file(text, 'second')
    assert [c.name for c in result.candidates] == ['first', 'second']
    assert result.selected == 'second'
    assert inspect_file(text, 'missing').error == 'NO_ELIGIBLE_FUNCTION'


def test_conditional_definitions_are_not_silently_enabled():
    result = inspect_file('#if 0\nint disabled(void){return 1;}\n#endif\n')
    assert result.error == 'NO_ELIGIBLE_FUNCTION'
    assert result.candidates[0].a_status == 'FAIL'


def test_original_function_comment_is_not_rewritten():
    result = inspect_file('int f(void){ /* 中文 */ return 1; }')
    assert '中文' in result.candidates[0].source_text


def test_cli_file_report(tmp_path):
    import json
    from codeart.cli import main
    src = tmp_path / 'input.c'
    output = tmp_path / 'output.c'
    report = tmp_path / 'report.json'
    src.write_text('#include <stdio.h>\nint f(int x){return x+1;}\n')
    assert main(['--file', str(src), '--function', 'f', '--output', str(output), '--report', str(report)]) == 0
    data = json.loads(report.read_text())
    assert data['status'] == 'OK'
    assert data['font_id'] == 'Roboto Mono Regular'
    assert data['cell_aspect'] == 0.5
    assert data['prepass']['selected'] == 'f'
    assert data['prepass']['ignored_lines'][0]['start_line'] == 1
    assert data['prepass']['validation_scope']
    assert data['checks']['token']['status'] == 'PASS'
    assert data['checks']['geometry']['status'] == 'PASS'
    assert data['checks']['compile']['status'] == 'PASS'
    assert data['checks']['behavior']['status'] == 'NOT_RUN'
    assert data['checks']['behavior']['reason'] == 'NO_FIXTURE'
    assert data['verification']['behavior_cases_compared'] == 0
    assert data['code_fill_ratio'] == data['coverage']['token']
    assert data['code_fill_ratio'] < 0.1
    assert data['code_fill_warning'] == 'Token density is low; filler comments occupy most allowed cells.'
    assert output.exists()


def test_cli_file_failure_report_is_unified(tmp_path):
    import json
    from codeart.cli import main
    src = tmp_path / 'disabled.c'
    report = tmp_path / 'report.json'
    src.write_text('#if 0\nint f(void){return 1;}\n#endif\n')
    assert main(['--file', str(src), '--function', 'f', '--report', str(report)]) == 1
    data = json.loads(report.read_text())
    from codeart.contracts import GenerationResult
    from codeart.presentation import describe_result
    assert set(data) == set(describe_result(GenerationResult())) | {'revision', 'prepass'}
    assert data['status'] == 'FAILED'
    assert data['verified'] is False
    assert 'revision' in data
    assert 'font_id' in data
    assert 'code_fill_ratio' in data
    assert 'code_fill_warning' in data
    assert data['prepass']['error'] == 'NO_ELIGIBLE_FUNCTION'
    assert data['diagnostics'] == []
    for name in ('token', 'geometry', 'compile', 'behavior'):
        assert data['checks'][name]['status'] == 'NOT_RUN'
        assert data['checks'][name]['reason'] == 'NO_ELIGIBLE_FUNCTION'


def test_web_prepass_endpoint():
    import json
    from threading import Thread
    from urllib.request import Request, urlopen
    from codeart.app import create_server
    server = create_server(0)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        payload = json.dumps({'source': '#include <stdio.h>\nint f(int x){return x;}'}).encode()
        request = Request(f'http://127.0.0.1:{server.server_port}/api/prepass', data=payload, headers={'Content-Type': 'application/json'})
        with urlopen(request) as response:
            data = json.load(response)
        assert data['selected'] == 'f'
        assert 'not the entire input program' in data['validation_scope']
    finally:
        server.shutdown()
        server.server_close()
        server.jobs.shutdown()
        worker.join()

def test_block_comment_directives_are_ignored():
    result = inspect_file('/*\n#if 0\n*/\nint f(void){return 1;}\n')
    assert result.selected == 'f'
    assert result.candidates[0].a_status == 'PASS'
    inside = inspect_file('int f(void){\n/*\n#if 0\n*/\nreturn 1;\n}\n')
    assert inside.selected == 'f'


def test_comment_endif_does_not_hide_a_conditional_region():
    result = inspect_file('#if 0\n/*\n#endif\n*/\nint f(void){return 1;}\n')
    assert result.error == 'NO_ELIGIBLE_FUNCTION'
    assert result.candidates[0].a_status == 'FAIL'


def test_function_pointer_and_parenthesised_names():
    text = 'int (*f(void))(int) { return 0; }\nint (g)(void) { return 1; }\n'
    result = inspect_file(text, 'f')
    assert result.selected == 'f'
    assert selected_source(result).startswith('int (*f(void))')
    assert inspect_file(text, 'g').selected == 'g'


def test_bom_crlf_and_lone_cr_are_normalised():
    for text in (
        '\ufeff#include <stdio.h>\nint f(void){return 1;}\n',
        '#include <stdio.h>\r\nint f(void){return 1;}\r\n',
        '#include <stdio.h>\rint f(void){return 1;}\r',
    ):
        result = inspect_file(text)
        assert result.selected == 'f'
        assert '\r' not in result.candidates[0].source_text


def test_same_line_prefix_and_suffix_are_reported():
    text = 'int a; int f(void){return 1;} int b(void){return 2;}\n'
    result = inspect_file(text, 'f')
    assert result.selected == 'f'
    assert result.ignored_lines == []
    assert len(result.ignored_segments) == 2
    assert result.ignored_segments[0]['start_column'] == 1
    assert result.ignored_segments[0]['end_column'] == 8
    assert result.ignored_segments[1]['start_column'] == 30


def test_main_and_duplicate_names_are_rejected():
    assert inspect_file('int (main)(void) { return 0; }\n').error == 'NO_ELIGIBLE_FUNCTION'
    assert inspect_file('int f(void){return 1;}\nint f(void){return 2;}\n').error == 'AMBIGUOUS_FUNCTION'


def test_web_file_mode_generates_extracted_function():
    import json
    import time
    from threading import Thread
    from urllib.request import Request, urlopen
    from codeart.app import create_server
    server = create_server(0)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        payload = json.dumps({
            'source': '#include <stdio.h>\nint f(int x){return x+1;}\nint main(void){return 0;}\n',
            'file_mode': True, 'function': 'f', 'shape': 'circle', 'scale': 1,
        }).encode()
        request = Request(base + '/api/generate', data=payload,
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=30) as response:
            job_id = json.load(response)['id']
        for _ in range(200):
            with urlopen(base + '/api/jobs/' + job_id, timeout=10) as response:
                job = json.load(response)
            if job['state'] == 'finished':
                break
            time.sleep(0.02)
        assert job['result']['prepass']['selected'] == 'f'
        assert job['source'] == 'int f(int x){return x+1;}'
        assert job['input_source'] == '#include <stdio.h>\nint f(int x){return x+1;}\nint main(void){return 0;}\n'
        assert job['file_mode'] is True
        assert job['function'] == 'f'
        assert job['result']['status'] == 'OK'
        assert job['result']['font_id'] == 'Roboto Mono Regular'
        assert job['result']['checks']['token']['status'] == 'PASS'
        assert job['result']['checks']['geometry']['status'] == 'PASS'
        assert job['result']['checks']['compile']['status'] == 'PASS'
        assert job['result']['checks']['behavior']['status'] == 'NOT_RUN'
        assert job['result']['checks']['behavior']['reason'] == 'NO_FIXTURE'
        assert job['result']['verification']['behavior_cases_compared'] == 0
        assert job['result']['prepass']['validation_scope']
        with urlopen(base + '/api/jobs/' + job_id + '/report.json', timeout=10) as response:
            report = json.load(response)
        assert report['result']['status'] == 'OK'
        assert report['result']['checks']['behavior']['reason'] == 'NO_FIXTURE'
    finally:
        server.shutdown()
        server.server_close()
        server.jobs.shutdown()
        worker.join()


def test_web_file_mode_failure_uses_common_report():
    import json
    from threading import Thread
    from urllib.request import Request, urlopen
    import time
    from codeart.app import create_server
    server = create_server(0)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        payload = json.dumps({
            'source': '#if 0\nint f(void){return 1;}\n#endif\n',
            'file_mode': True, 'function': 'f', 'shape': 'circle', 'scale': 1,
        }).encode()
        request = Request(base + '/api/generate', data=payload,
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=5) as response:
            assert response.status == 202
            job_id = json.load(response)['id']
        for _ in range(200):
            with urlopen(base + '/api/jobs/' + job_id, timeout=5) as response:
                job = json.load(response)
            if job['state'] == 'finished':
                break
            time.sleep(0.02)
        assert job['state'] == 'finished'
        data = job['result']
        assert data['status'] == 'FAILED'
        assert data['error'] == 'NO_ELIGIBLE_FUNCTION'
        assert data['prepass']['error'] == 'NO_ELIGIBLE_FUNCTION'
        assert 'revision' in job
        assert 'font_id' in data
        assert 'code_fill_ratio' in data
        assert 'code_fill_warning' in data
        for name in ('token', 'geometry', 'compile', 'behavior'):
            assert data['checks'][name]['status'] == 'NOT_RUN'
            assert data['checks'][name]['reason'] == 'NO_ELIGIBLE_FUNCTION'
        with urlopen(base + '/api/jobs/' + job_id + '/report.json', timeout=5) as response:
            assert json.load(response)['result'] == data
    finally:
        server.shutdown()
        server.server_close()
        server.jobs.shutdown()
        worker.join()


def test_macro_continuation_is_not_a_function_definition():
    text = '#define BODY ' + chr(92) + chr(10) + 'int fake(void){return 1;}\nint real(void){return 2;}'
    result = inspect_file(text)
    assert [c.name for c in result.candidates] == ['real']
    assert result.selected == 'real'

def test_code_fill_note_is_neutral_and_uses_the_ten_percent_threshold():
    from codeart.contracts import GenerationResult, RenderedCode
    from codeart.presentation import LOW_CODE_FILL_WARNING, describe_result

    def report_for(ratio):
        rendered = RenderedCode("", {}, 0.99, ratio, 0.99 - ratio, {"block": 0, "line": 0})
        return describe_result(GenerationResult(rendered=rendered))

    low = report_for(0.09)
    high = report_for(0.10)
    assert low["code_fill_warning"] == LOW_CODE_FILL_WARNING
    assert "smaller shape" not in low["code_fill_warning"]
    assert high["code_fill_warning"] is None
