from PIL import Image
import pytest

from verifile.gemma import Gemma4Reviewer


def _sample_report_and_image():
    img = Image.new('RGB', (120, 80), '#ffffff')
    report = {
        'file': {'type_detected': 'png'},
        'forensics': {
            'metadata': {'width': 120, 'height': 80, 'format': 'PNG'},
            'findings': [],
            'overlay_diagnostics': [],
            'recapture_diagnostics': [],
            'reference_comparison': {'status': 'not_provided'},
        },
    }
    return report, [img]


def test_local_gemma_success_does_not_trigger_gemini_fallback(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'fake-gemini-key')
    report, pages = _sample_report_and_image()

    gemini_called = False

    def fake_gemini(*args, **kwargs):
        nonlocal gemini_called
        gemini_called = True
        return '{"summary": "dari gemini"}'

    reviewer = Gemma4Reviewer(gemini_caller=fake_gemini)
    reviewer.pipe = lambda **kwargs: [{'generated_text': '{"summary": "dari gemma lokal"}'}]

    result = reviewer.review(report, pages)

    assert result['status'] == 'completed'
    assert result['provider'] == 'local_transformers'
    assert result['analysis']['summary'] == 'dari gemma lokal'
    assert gemini_called is False


def test_falls_back_to_gemini_api_when_local_gemma_fails(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'test-api-key')
    monkeypatch.setenv('GEMINI_FALLBACK', '1')
    report, pages = _sample_report_and_image()
    report['forensics']['metadata']['text_preview'] = 'Rekening 12345678901234'

    captured = {}

    def fake_gemini(*, api_key, model_id, system_prompt, user_prompt, images):
        captured['api_key'] = api_key
        captured['model_id'] = model_id
        captured['system_prompt'] = system_prompt
        captured['user_prompt'] = user_prompt
        captured['image_count'] = len(images)
        return '{"summary": "hasil fallback gemini", "ai_generation": "tidak dapat dipastikan"}'

    reviewer = Gemma4Reviewer(
        model_id='google/gemma-4-E2B-it',
        gemini_model_id='gemini-2.5-flash',
        gemini_caller=fake_gemini,
    )

    def broken_load():
        raise RuntimeError('CUDA GPU tidak tersedia.')

    reviewer.load = broken_load

    result = reviewer.review(report, pages)

    assert result['status'] == 'completed_gemini_fallback'
    assert result['provider'] == 'gemini_api'
    assert result['model'] == 'gemini-2.5-flash'
    assert 'CUDA GPU tidak tersedia' in result['fallback_reason']
    assert result['analysis']['summary'] == 'hasil fallback gemini'
    assert captured['api_key'] == 'test-api-key'
    assert captured['image_count'] == 1
    assert '12345678901234' not in captured['user_prompt']
    assert '**********1234' in captured['user_prompt']


def test_raises_original_error_when_no_gemini_api_key_set(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    report, pages = _sample_report_and_image()

    reviewer = Gemma4Reviewer()

    def broken_load():
        raise RuntimeError('CUDA GPU tidak tersedia.')

    reviewer.load = broken_load

    with pytest.raises(RuntimeError, match='CUDA GPU tidak tersedia'):
        reviewer.review(report, pages)


def test_gemini_only_mode_skips_local_gemma_load(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'direct-key')
    monkeypatch.setenv('GEMINI_ONLY', '1')
    report, pages = _sample_report_and_image()

    load_called = False

    def should_not_load():
        nonlocal load_called
        load_called = True

    reviewer = Gemma4Reviewer(
        gemini_model_id='gemini-2.5-flash',
        gemini_caller=lambda **kwargs: '{"summary": "langsung gemini"}',
    )
    reviewer.load = should_not_load

    result = reviewer.review(report, pages)

    assert load_called is False
    assert result['status'] == 'completed_gemini_api'
    assert result['provider'] == 'gemini_api'
    assert result['analysis']['summary'] == 'langsung gemini'


def test_reports_both_errors_when_local_and_gemini_fallback_both_fail(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'bad-key')
    report, pages = _sample_report_and_image()

    def failing_gemini(**kwargs):
        raise ValueError('Invalid API key')

    reviewer = Gemma4Reviewer(gemini_caller=failing_gemini)
    reviewer.load = lambda: (_ for _ in ()).throw(RuntimeError('No GPU'))

    with pytest.raises(RuntimeError, match='No GPU.*Invalid API key'):
        reviewer.review(report, pages)


def test_loads_gemini_api_key_from_dotenv_file(monkeypatch, tmp_path):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    env_file = tmp_path / '.env'
    env_file.write_text('GEMINI_API_KEY=dotenv-secret-key\nGEMINI_MODEL_ID=gemini-2.5-flash\n', encoding='utf-8')

    report, pages = _sample_report_and_image()
    seen_key = {}

    def fake_gemini(*, api_key, model_id, **kwargs):
        seen_key['api_key'] = api_key
        seen_key['model_id'] = model_id
        return '{"summary": "dari dotenv"}'

    reviewer = Gemma4Reviewer(gemini_caller=fake_gemini, dotenv_path=env_file)
    reviewer.load = lambda: (_ for _ in ()).throw(RuntimeError('CUDA GPU tidak tersedia.'))

    result = reviewer.review(report, pages)
    assert result['status'] == 'completed_gemini_fallback'
    assert seen_key == {'api_key': 'dotenv-secret-key', 'model_id': 'gemini-2.5-flash'}


def test_stdlib_gemini_rest_transport_formats_request_and_parses_response(monkeypatch):
    import json
    import sys
    import urllib.request
    from verifile.gemma import _call_gemini_api

    monkeypatch.setitem(sys.modules, 'google', None)
    monkeypatch.setitem(sys.modules, 'google.genai', None)

    captured_req = {}

    class FakeHTTPResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({
                'candidates': [{'content': {'parts': [{'text': '{"summary": "via rest"}'}]}}]
            }).encode('utf-8')

    def fake_urlopen(req, timeout=0):
        captured_req['url'] = req.full_url
        captured_req['api_key'] = req.headers.get('X-goog-api-key')
        captured_req['body'] = json.loads(req.data.decode('utf-8'))
        captured_req['timeout'] = timeout
        return FakeHTTPResponse()

    monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)

    img = Image.new('RGB', (40, 30), '#abcdef')
    raw = _call_gemini_api(
        api_key='rest-key-123',
        model_id='gemini-2.5-flash',
        system_prompt='SYS',
        user_prompt='USR',
        images=[img],
    )

    assert json.loads(raw)['summary'] == 'via rest'
    assert captured_req['url'].endswith('/models/gemini-2.5-flash:generateContent')
    assert captured_req['api_key'] == 'rest-key-123'
    assert captured_req['body']['system_instruction']['parts'][0]['text'] == 'SYS'
    assert captured_req['body']['generationConfig']['responseMimeType'] == 'application/json'
    assert len(captured_req['body']['contents'][0]['parts']) == 2



