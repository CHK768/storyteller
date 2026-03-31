import os
import re
import json
import base64
import subprocess
import requests
from flask import Flask, render_template, request, jsonify, Response, stream_with_context

app = Flask(__name__)

SILICONFLOW_API_KEY = os.environ.get('SILICONFLOW_API_KEY', '')
JIMENG_API_KEY = os.environ.get('JIMENG_API_KEY', '')
IMAGE_MODEL = os.environ.get('IMAGE_MODEL', 'doubao-seedream-3-0-t2i-250415')
CLAUDE_BIN = os.environ.get('CLAUDE_BIN', 'claude')


def research_theme(theme: str) -> str:
    """多轮搜索：人物/事件背景 + 关键事件 + 最新动态"""
    try:
        prompt = f"""请对「{theme}」进行深度调研，分三个维度搜索：
1. 基本背景：这个人/事件是谁/什么，核心经历、身份、成就
2. 关键事件：最重要的几个转折点或标志性时刻（具体时间、地点、细节）
3. 最新动态：近期发生了什么，现状如何

要求：
- 每个维度各2-3条具体事实，有时间/数字/细节的那种
- 不要泛泛而谈，要有真实可查的具体信息
- 如果是真实人物，聚焦真实发生的事件"""
        result = subprocess.run(
            [CLAUDE_BIN, '-p', prompt, '--allowedTools', 'WebSearch'],
            capture_output=True, text=True, timeout=90
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return ''


def generate_story(theme: str, research: str) -> dict:
    research_section = ''
    if research:
        research_section = f"""
以下是关于「{theme}」的背景资料，请结合这些信息让故事更真实生动：
{research}
"""

    prompt = f"""请根据以下背景资料，为「{theme}」创作一部写实风格的图文故事绘本。
{research_section}
只返回如下格式的 JSON，不要任何其他文字：
{{
  "title": "故事标题",
  "art_style": "realistic documentary illustration style in English, cinematic lighting, detailed and authentic",
  "pages": [
    {{
      "page_num": 1,
      "text": "这一页故事文字，2-3句中文，基于真实事件",
      "image_prompt": "realistic scene description in English, specific location/time/people, photorealistic or documentary illustration style"
    }}
  ]
}}

要求：
- 生成 7-9 页，按时间线讲述真实发生的事件，有完整叙事弧
- 故事文字用中文，每页 2-4 句，语言有张力，忠于史实
- 必须融入调研资料中的具体细节：真实地点、时间、数字、人名
- 不要虚构情节，但可以用文学语言描写已发生的真实场景
- image_prompt 全英文，描述真实场景：具体地点特征、人物外貌、历史时代感
- 画风：cinematic documentary illustration, realistic proportions, dramatic lighting, historical authenticity"""

    result = subprocess.run(
        [CLAUDE_BIN, '-p', prompt],
        capture_output=True, text=True, timeout=300
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or '故事生成失败')

    content = result.stdout.strip()
    match = re.search(r'\{[\s\S]*\}', content)
    if not match:
        raise ValueError(f'响应中未找到 JSON：{content[:200]}')
    raw = match.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        from json_repair import repair_json
        return json.loads(repair_json(raw))


def generate_image(prompt: str, art_style: str) -> str:
    full_prompt = f"{prompt}, {art_style}"

    # 优先用即梦，备选硅基流动
    api_key = JIMENG_API_KEY or SILICONFLOW_API_KEY
    if JIMENG_API_KEY:
        endpoint = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
        payload = {"model": IMAGE_MODEL, "prompt": full_prompt, "size": "1024x576", "watermark": False}
        resp_key = lambda d: d.get('data', [{}])[0].get('url', '')
    else:
        endpoint = "https://api.siliconflow.cn/v1/images/generations"
        payload = {"model": "Kwai-Kolors/Kolors", "prompt": full_prompt, "image_size": "1024x576"}
        resp_key = lambda d: (d.get('images') or [{}])[0].get('url', '')

    try:
        resp = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload, timeout=90
        )
        if resp.status_code == 200:
            url = resp_key(resp.json())
            if url:
                dl = requests.get(url, timeout=30)
                if dl.status_code == 200:
                    ct = dl.headers.get('content-type', 'image/jpeg').split(';')[0]
                    b64 = base64.b64encode(dl.content).decode()
                    return f"data:{ct};base64,{b64}"
    except Exception:
        pass
    return ''


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    data = request.json
    theme = (data.get('theme') or '').strip()

    if not theme:
        return jsonify({'error': '请输入主题或名字'}), 400
    if not JIMENG_API_KEY and not SILICONFLOW_API_KEY:
        return jsonify({'error': '未设置图片 API Key'}), 500

    def stream():
        try:
            yield f"data: {json.dumps({'type': 'status', 'message': '🔍 正在搜索主题背景...'}, ensure_ascii=False)}\n\n"
            research = research_theme(theme)

            if research:
                yield f"data: {json.dumps({'type': 'status', 'message': '✍️ 已获取背景资料，正在构思故事...'}, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'status', 'message': '✍️ 正在构思故事...'}, ensure_ascii=False)}\n\n"

            story = generate_story(theme, research)
            n = len(story['pages'])

            yield f"data: {json.dumps({'type': 'story', 'data': story}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'status', 'message': f'🎨 故事完成！开始绘制 {n} 张插图...'}, ensure_ascii=False)}\n\n"

            art_style = story.get('art_style', 'children book illustration, soft watercolor, warm colors')

            for i, page in enumerate(story['pages']):
                msg = f'🖌️ 绘制第 {i+1}/{n} 页...'
                yield f"data: {json.dumps({'type': 'status', 'message': msg}, ensure_ascii=False)}\n\n"
                image_url = generate_image(page['image_prompt'], art_style)
                yield f"data: {json.dumps({'type': 'image', 'page_index': i, 'url': image_url}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

        except json.JSONDecodeError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'故事格式解析失败：{str(e)}'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(stream()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'}
    )


if __name__ == '__main__':
    app.run(debug=True, port=5001, threaded=True)
